/*
  fct_gong_call_classification
  ─────────────────────────────
  LLM-based call classification pipeline:
    Stage 1: Classify call type (First Meeting / Business Validation / POC / Existing Customer / Skip)
    Stage 2: AEP score + use_case + initiative analysis (skips "Skip" calls)

  Dependencies:
    - GONG.GONG_DATA_CLOUD.CALLS
    - GONG.GONG_DATA_CLOUD.CALL_TRANSCRIPTS
    - GONG.GONG_DATA_CLOUD.CONVERSATION_PARTICIPANTS
    - GONG.GONG_DATA_CLOUD.USERS (for Port team identification)

  NOTE: call_type_prompt_fully_verified = FALSE means the Stage 1 classifier prompt
  includes two gap-filled sections (Existing Customer + Skip) not confirmed against
  the original n8n workflow source. Flip to TRUE after confirming.
*/

-- =============================================================================
-- STAGING: Filtered calls (completed, non-trivial duration, not deleted)
-- =============================================================================
CREATE OR REPLACE VIEW PORT_ANALYTICS_DEV.DWH.stg_gong_calls_filtered AS
SELECT
  CONVERSATION_KEY,
  TITLE,
  STATUS,
  EFFECTIVE_START_DATETIME,
  ROUND(BROWSER_DURATION_SEC / 60.0, 1) AS duration_min
FROM GONG.GONG_DATA_CLOUD.CALLS
WHERE STATUS = 'COMPLETED'
  AND IS_DELETED = FALSE
  AND BROWSER_DURATION_SEC >= 120  -- skip calls under 2 minutes (noise/test calls)
;

-- =============================================================================
-- STAGING: Transcript flattened to plain text (first 5000 chars for Stage 1)
-- =============================================================================
CREATE OR REPLACE VIEW PORT_ANALYTICS_DEV.DWH.stg_gong_call_transcripts AS
SELECT
  ct.CONVERSATION_KEY,
  LISTAGG(
    s.value:text::STRING, ' '
  ) WITHIN GROUP (ORDER BY seg.index, s.index) AS transcript_text
FROM GONG.GONG_DATA_CLOUD.CALL_TRANSCRIPTS ct,
  LATERAL FLATTEN(input => ct.TRANSCRIPT) seg,
  LATERAL FLATTEN(input => seg.value:sentences) s
WHERE ct.IS_DELETED = FALSE
  AND ct.TRANSCRIPT IS NOT NULL
GROUP BY ct.CONVERSATION_KEY
;

-- =============================================================================
-- STAGING: Participant aggregation per call
--   - external_emails: semicolon-separated list of non-company participant emails
--   - port_team: comma-separated list of Port employees on the call (name + title)
-- =============================================================================
CREATE OR REPLACE VIEW PORT_ANALYTICS_DEV.DWH.stg_gong_call_participants AS
SELECT
  cp.CONVERSATION_KEY,
  LISTAGG(
    CASE WHEN cp.AFFILIATION = 'non_company' THEN cp.EMAIL_ADDRESS END,
    '; '
  ) WITHIN GROUP (ORDER BY cp.EMAIL_ADDRESS) AS external_emails,
  LISTAGG(
    CASE WHEN cp.AFFILIATION = 'company'
         THEN COALESCE(u.FIRST_NAME || ' ' || u.LAST_NAME, cp.NAME)
              || COALESCE(' (' || NULLIF(u.TITLE,'') || ')', '')
    END,
    ', '
  ) WITHIN GROUP (ORDER BY u.LAST_NAME) AS port_team
FROM GONG.GONG_DATA_CLOUD.CONVERSATION_PARTICIPANTS cp
LEFT JOIN GONG.GONG_DATA_CLOUD.USERS u
  ON cp.USER_ID = u.USER_ID
  AND u.IS_DELETED = FALSE
GROUP BY cp.CONVERSATION_KEY
;

-- =============================================================================
-- MAIN TABLE: Two-stage LLM classification
-- =============================================================================
CREATE OR REPLACE TABLE PORT_ANALYTICS_DEV.DWH.fct_gong_call_classification AS

WITH stage1 AS (
  SELECT
    c.CONVERSATION_KEY,
    SNOWFLAKE.CORTEX.COMPLETE(
      'claude-sonnet-4-6',
      [
        {'role':'system','content': $stage1_prompt$You are a sales call classifier for Port (an internal developer platform company).

Given call metadata and the beginning of a transcript, classify the call into exactly one of these types. Return JSON: {"call_type": "<type>"}

=== FIRST MEETING ===
The first real interaction between Port and a prospect. Signals:
- Introductions happening ("tell us about your company", "what does Port do")
- Discovery questions about the prospect's current setup
- High-level Port overview/pitch being given
- No prior shared context or follow-ups referenced
- Participants are meeting each other for the first time

=== BUSINESS VALIDATION ===
A mid-funnel call focused on proving business value, aligning stakeholders, or scoping a potential deal. Signals:
- ROI / business case discussion
- Multiple stakeholders joining from the prospect side
- References to prior meetings or a demo already seen
- Discussion of pricing, packaging, or procurement
- Security / compliance review
- Technical architecture review with a business framing
- Champion building / stakeholder alignment

=== POC ===
A call related to an active proof-of-concept or technical evaluation. Signals:
- Discussion of specific technical implementation details
- References to a trial/POC environment or sandbox
- Troubleshooting or configuration help
- Progress check on evaluation criteria or success metrics
- "Technical implementa"tion timeline or milestones being discussed
- Integration specifics (APIs, webhooks, SSO, SCM)

=== EXISTING CUSTOMER === [NOT VERIFIED AGAINST SOURCE — label confirmed via AEP scorer prompt, behavior definition inferred]
The account is already a paying customer. Call concerns an existing deployment, renewal, expansion, or support — not a net-new evaluation. Signals:
- References to production usage, live environment, existing deployment
- Renewal or expansion discussion
- Support / troubleshooting for a live system
- QBR or success review
- Upsell into new team or use case within same org

=== SKIP === [NOT VERIFIED AGAINST SOURCE — label confirmed via workflow routing logic only]
Internal call, personal call, or call with no sales relevance. Not a customer-facing sales conversation at all. Signals:
- All participants are @port.io or @getport.io
- Internal standup, 1:1, planning session
- No external participants
- Clearly non-sales content (HR, social, recruiting)
$stage1_prompt$},
        {'role':'user','content':
          'Call Title: ' || c.TITLE ||
          E'\nParticipant Emails: ' || COALESCE(p.external_emails, '(none)') ||
          E'\nPort Team: ' || COALESCE(p.port_team, '(unknown)') ||
          E'\nDuration: ' || c.duration_min || ' minutes' ||
          E'\n\nTranscript (first 5000 chars):\n' || LEFT(t.transcript_text, 5000)}
      ],
      {'temperature': 0, 'max_tokens': 500}
    ):content::STRING AS classifier_raw_output
  FROM PORT_ANALYTICS_DEV.DWH.stg_gong_calls_filtered c
  JOIN PORT_ANALYTICS_DEV.DWH.stg_gong_call_participants p USING (CONVERSATION_KEY)
  JOIN PORT_ANALYTICS_DEV.DWH.stg_gong_call_transcripts t USING (CONVERSATION_KEY)
),

parsed1 AS (
  SELECT
    CONVERSATION_KEY,
    classifier_raw_output,
    TRY_PARSE_JSON(classifier_raw_output):call_type::STRING AS call_type
  FROM stage1
),

stage2 AS (
  SELECT
    p1.CONVERSATION_KEY,
    p1.call_type,
    SNOWFLAKE.CORTEX.COMPLETE(
      'claude-sonnet-4-6',
      [
        {'role':'system','content': $stage2_prompt$You are an expert sales call analyst for Port, a developer platform company.

Analyze the call and return a JSON object with these fields:

{
  "score": "High" | "Medium" | "Low",
  "use_case": "<primary use case discussed>",
  "initiated_by": "Port" | "Customer" | "Unclear",
  "trigger_reason": "<what triggered this conversation — e.g. pain point, event, referral, outbound sequence>"
}

Scoring rubric:
- High: Strong buying signals, clear pain, budget/timeline mentioned, multiple stakeholders engaged, or active evaluation underway
- Medium: Interest shown but no urgency, single thread, early exploration, or unclear decision process
- Low: Polite but no real engagement, no follow-up committed, skeptical/resistant, or just gathering info with no intent

For use_case, identify the primary use case from: developer portal, service catalog, self-service actions, software catalog, scorecards, microservice standards, cloud resource management, CI/CD visibility, onboarding, platform engineering, or describe briefly if none fit.

For initiated_by: who drove the meeting happening — did Port reach out (outbound, sequence, cold call) or did the customer initiate (inbound demo request, referral, event follow-up)?

For trigger_reason: what specific event or pain caused this conversation to happen now? Be specific (e.g. "new VP of Platform mandate", "Backstage too complex", "developer survey results", "saw Port at KubeCon").$stage2_prompt$},
        {'role':'user','content':
          'Call Type: ' || p1.call_type ||
          E'\nCall: ' || c.TITLE ||
          E'\nDuration: ' || c.duration_min || ' minutes' ||
          E'\n\nTranscript:\n' || LEFT(t.transcript_text, 30000)}
      ],
      {'temperature': 0, 'max_tokens': 1500}
    ):content::STRING AS analysis_raw_output
  FROM parsed1 p1
  JOIN PORT_ANALYTICS_DEV.DWH.stg_gong_calls_filtered c USING (CONVERSATION_KEY)
  JOIN PORT_ANALYTICS_DEV.DWH.stg_gong_call_transcripts t USING (CONVERSATION_KEY)
  WHERE p1.call_type IS NOT NULL
    AND p1.call_type != 'Skip'
)

SELECT
  s2.CONVERSATION_KEY,
  s2.call_type,
  TRY_PARSE_JSON(s2.analysis_raw_output):score::STRING       AS aep_score,
  TRY_PARSE_JSON(s2.analysis_raw_output):use_case::STRING    AS aep_use_case,
  TRY_PARSE_JSON(s2.analysis_raw_output):initiated_by::STRING AS aep_initiated_by,
  TRY_PARSE_JSON(s2.analysis_raw_output):trigger_reason::STRING AS aep_trigger_reason,
  s2.analysis_raw_output,
  p1.classifier_raw_output AS stage1_raw_output,
  FALSE AS call_type_prompt_fully_verified,
  CURRENT_TIMESTAMP() AS processed_at
FROM stage2 s2
JOIN parsed1 p1 USING (CONVERSATION_KEY)
;
