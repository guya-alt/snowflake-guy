-- Closed-Lost Reason Validation
--
-- Validates whether reps' HubSpot closed-lost reasons (picklist) are corroborated
-- by evidence from Gong call transcripts and the rep's free-text Closed Lost Details.
--
-- Two-agent pipeline:
--   Agent 1: classifies each deal's evidence vs the stated reason (yes/likely_yes/likely_no/no/unclear/unknown).
--   Agent 2: reviews Agent 1's "no" and "likely_no" verdicts for self-contradiction.
--
-- Prerequisites before each run:
--   1. Export deals from HubSpot (include Record ID + Closed Lost Details columns).
--   2. Upload the CSV to a temp stage and create the hubspot_closed_lost_details table:
--        CREATE OR REPLACE TEMPORARY STAGE hubspot_closed_lost_stg;
--        CREATE OR REPLACE TEMPORARY FILE FORMAT hubspot_csv_fmt
--          TYPE='CSV' FIELD_OPTIONALLY_ENCLOSED_BY='"' SKIP_HEADER=1 NULL_IF=('');
--        PUT 'file:///path/to/export.csv' @hubspot_closed_lost_stg AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
--        CREATE OR REPLACE TEMPORARY TABLE hubspot_closed_lost_details AS
--          SELECT $1::STRING AS RECORD_ID, $32::STRING AS CLOSED_LOST_DETAILS
--          FROM @hubspot_closed_lost_stg/export.csv.gz (FILE_FORMAT => hubspot_csv_fmt)
--          WHERE $32 IS NOT NULL AND $32 != '';
--   3. Run this query.

WITH lost_deals AS (
    SELECT
        d.SK_DEAL,
        d.DEAL_CRM_ID,
        d.DEAL_NAME,
        dc.COMPANY_NAME,
        d.PIPELINE,
        d.DEAL_TYPE,
        d.DEAL_TEAM_NAME,
        d.DEAL_STAGE,
        d.DEAL_CLOSED_DATE,
        d.DEAL_CREATED_DATE,
        d.SALES_CYCLE_DAYS,
        d.DEAL_TOTAL_ARR,
        d.DEAL_NET_NEW_ARR,
        d.CLOSED_LOST_REASON,
        sales_e.DISPLAY_NAME AS SALES_OWNER
    FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS d
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY dc
           ON d.SK_COMPANY = dc.SK_COMPANY
          AND COALESCE(dc.COMPANY_NAME, '') NOT ILIKE '%test%'
          AND COALESCE(dc.COMPANY_NAME, '') != 'Port'
          AND dc._IS_DELETED = FALSE
          AND dc.ARCHIVED    = FALSE
    LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_EMPLOYEE sales_e ON d.SK_SALES_OWNER = sales_e.SK_EMPLOYEE
    WHERE d.IS_CLOSED = TRUE
      AND d.DEAL_TEAM_NAME IS NOT NULL AND d.DEAL_TEAM_NAME NOT ILIKE 'sdr%'
      AND d.DEAL_TOTAL_ARR IS NOT NULL
      AND d.qualified_date is not null
      AND d.DEAL_TYPE = 'newbusiness'
      -- Exclude if ANY semicolon-delimited part of the reason is a non-signal reason.
      -- Pad with ';' and normalise whitespace around delimiters so ';no_show;' matches
      -- whether the part is first, middle, last, or the whole string.
      AND NOT (
           ';' || REGEXP_REPLACE(LOWER(TRIM(d.CLOSED_LOST_REASON)), '\\s*;\\s*', ';') || ';' LIKE '%;other;%'
        OR ';' || REGEXP_REPLACE(LOWER(TRIM(d.CLOSED_LOST_REASON)), '\\s*;\\s*', ';') || ';' LIKE '%;no_show;%'
        OR ';' || REGEXP_REPLACE(LOWER(TRIM(d.CLOSED_LOST_REASON)), '\\s*;\\s*', ';') || ';' LIKE '%;unable to connect;%'
      )
      AND d.IS_WON    = FALSE
      AND d.CLOSED_LOST_REASON IS NOT NULL AND d.CLOSED_LOST_REASON != ''
      AND d.DEAL_CLOSED_DATE >= DATE '2025-07-01'
      AND d.DEAL_CLOSED_DATE <  DATEADD('day', -2, CURRENT_DATE)
    -- QUALIFY ROW_NUMBER() OVER (ORDER BY d.DEAL_CLOSED_DATE DESC) <= 250
),
lost_deals_cat AS (
    SELECT *,
        ARRAY_DISTINCT(ARRAY_COMPACT(ARRAY_CONSTRUCT(
            IFF(CLOSED_LOST_REASON ILIKE '%no_show%'
                OR CLOSED_LOST_REASON ILIKE '%unable to connect%'
                OR CLOSED_LOST_REASON ILIKE '%UNQ%',                'No Engagement', NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%bad timing%'
                OR CLOSED_LOST_REASON ILIKE '%early stage%',         'Timing',        NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%not right%'
                OR CLOSED_LOST_REASON ILIKE '%persona%'
                OR CLOSED_LOST_REASON ILIKE '%consultant%'
                OR CLOSED_LOST_REASON ILIKE '%partnership%',         'Fit',           NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%no value%'
                OR CLOSED_LOST_REASON ILIKE '%product%'
                OR CLOSED_LOST_REASON ILIKE '%freemium%'
                OR CLOSED_LOST_REASON ILIKE '%on-prem%',             'Value/Product', NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%competition%'
                OR CLOSED_LOST_REASON ILIKE '%competitor%'
                OR CLOSED_LOST_REASON ILIKE '%internal build%'
                OR CLOSED_LOST_REASON ILIKE '%backstage%'
                OR CLOSED_LOST_REASON ILIKE '%spotify%'
                OR CLOSED_LOST_REASON ILIKE '%cortex%'
                OR CLOSED_LOST_REASON ILIKE '%harness%'
                OR CLOSED_LOST_REASON ILIKE '%opslevel%',            'Competitive',   NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%budget%'
                OR CLOSED_LOST_REASON ILIKE '%price%',               'Commercial',    NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%champion%'
                OR CLOSED_LOST_REASON ILIKE '%churn%',               'Sponsorship',   NULL),
            IFF(CLOSED_LOST_REASON ILIKE '%security%',               'Security',      NULL)
        ))) AS HS_LOST_CATEGORIES
    FROM lost_deals
),
recent_calls AS (
    SELECT
        SK_DEAL,
        COUNT(*)              AS CALLS_ANALYZED,
        MAX(CALL_DATE)        AS LATEST_CALL_DATE,
        MIN(CALL_DATE)        AS EARLIEST_ANALYZED_CALL_DATE,
        LEFT(
            LISTAGG(SPOTLIGHT_TEXT, '\n--- next call ---\n')
                WITHIN GROUP (ORDER BY rn ASC),
            4000
        )                                                           AS SPOTLIGHT_TEXT,
        ARRAY_AGG(SK_CONVERSATION) WITHIN GROUP (ORDER BY rn ASC)   AS ANALYZED_SK_CONVERSATIONS
    FROM (
        SELECT
            df.ASSOCIATED_SK AS SK_DEAL,
            f.SK_CONVERSATION,
            f.EFFECTIVE_START_DATETIME::DATE AS CALL_DATE,
            CONCAT_WS('\n',
                NULLIF(COALESCE(f.CALL_SPOTLIGHT_BRIEF, ''), ''),
                NULLIF(COALESCE(ARRAY_TO_STRING(f.CALL_SPOTLIGHT_KEY_POINTS, '\n'), ''), ''),
                NULLIF(COALESCE(f.CALL_SPOTLIGHT_NEXT_STEPS, ''), '')
            ) AS SPOTLIGHT_TEXT,
            ROW_NUMBER() OVER (PARTITION BY df.ASSOCIATED_SK
                               ORDER BY f.EFFECTIVE_START_DATETIME DESC) AS rn
        FROM PORT_ANALYTICS_PROD.DWH.MV_CALL_ASSOCIATED_DEAL_FLAT df
        JOIN PORT_ANALYTICS_PROD.DWH.FACT_CALL     f  ON df.SK_CONVERSATION = f.SK_CONVERSATION
        JOIN lost_deals_cat                        ld ON ld.SK_DEAL         = df.ASSOCIATED_SK
        WHERE f.EFFECTIVE_START_DATETIME <= ld.DEAL_CLOSED_DATE
    )
    WHERE rn <= 3
      AND LENGTH(TRIM(SPOTLIGHT_TEXT)) > 0
    GROUP BY SK_DEAL
),
gong_classified AS (
    SELECT
        SK_DEAL,
        CALLS_ANALYZED,
        LATEST_CALL_DATE,
        EARLIEST_ANALYZED_CALL_DATE,
        ANALYZED_SK_CONVERSATIONS,
        SPOTLIGHT_TEXT,
        AI_CLASSIFY(
            SPOTLIGHT_TEXT,
            ['No Engagement','Timing','Fit','Value/Product','Competitive',
             'Commercial','Sponsorship','Security','Other'],
            {'output_mode': 'multi'}
        ):labels::ARRAY AS GONG_LOST_CATEGORY
    FROM recent_calls
),
ai_reason_judgment AS (
    SELECT
        ld.SK_DEAL,
        AI_COMPLETE(
            'claude-4-sonnet',
            -- ROLE ------------------------------------------------------------
            'You are a sales-operations analyst auditing CRM data hygiene. Your job: decide whether the closed-lost reason (a structured picklist value) a rep selected in HubSpot is corroborated by the available evidence. The evidence comes from two sources: (1) the rep''s own free-text Closed Lost Details field, and (2) Gong call transcripts from the last 2-3 recorded calls. The picklist reason is WHAT YOU ARE VALIDATING — the details and calls are WHAT YOU VALIDATE IT AGAINST.' ||

            -- WHO WE ARE ------------------------------------------------------
            ' WHO WE ARE: We are Port — also written port.io, getport, or getport.io. We sell an Internal Developer Portal (IDP). Every deal you see was LOST by us. Any mention of Port / port.io / getport / getport.io in the transcript refers to US, the vendor, never to a competitor or a product the prospect chose instead.' ||
            ' OUR COMPETITORS: Backstage (Spotify''s open-source IDP), Cortex / cortex.io, Harness IDP, OpsLevel, and the prospect building their own portal in-house (build-vs-buy). If the prospect signals they are going with, already run, or prefer any of these, that is a COMPETITIVE loss.' ||

            -- HUBSPOT VOCABULARY ----------------------------------------------
            ' HOW REPS USE THE HUBSPOT REASON FIELD (decode these literally wrong-sounding labels):' ||
            '   - "Early stage" = the PROSPECT is not ready to buy yet: no funding, no exec sponsor, immature platform practice, still scoping internally. It does NOT mean the prospect company is an early-stage startup.' ||
            '   - "Bad timing" / "Timing" = the purchase was deferred: next fiscal year, next budget cycle, pending re-org, waiting on leadership.' ||
            '   - "Not right company/ persona" = wrong buyer, wrong company profile, consultant/partner rather than end user.' ||
            '   - "No value" = the prospect sees no value in our solution — they do not believe an IDP (or Port specifically) solves a real problem for them. This is about perceived value, not price.' ||
            '   - "Product" = we lacked a required capability (on-prem, specific integration, missing feature) or the product did not meet their technical requirements.' ||
            '   - "Competition" / "Internal Build" = they chose a competitor or their own build.' ||
            '   - "Budget" / "Price" = cost was the blocker.' ||
            '   - "Champion left" = our sponsor/champion changed roles, left the company, or was reassigned.' ||
            '   - "Company cuts" = the org is in financial distress — layoffs, budget cuts, hiring freezes, failed acquisitions, restructuring, or any macro event that killed their ability to buy. This is NOT the same as "Budget" (where the org is healthy but the price is too high). Company cuts means the org itself is contracting.' ||
            '   - Reasons may be MULTI-PART, separated by commas or semicolons (e.g. "Bad timing;Budget;No value"). Corroborating ANY ONE part is enough to support the reason. Before you assign a verdict, list every part of the stated reason and check each one independently against the transcript.' ||

            -- THE CENTRAL PITFALL --------------------------------------------
            ' THE CENTRAL PITFALL — READ CAREFULLY: Every deal here is closed-lost, but the calls you are reading happened BEFORE the deal died. Deals almost never die on a recorded call. They die afterwards: the prospect goes silent, declines by email, an exec kills the budget, or the champion moves on. So a transcript full of enthusiasm, scheduled next steps, POC planning, and forward momentum is COMPLETELY NORMAL for a lost deal. Engagement is NEUTRAL evidence.' ||
            ' Therefore you must NEVER reason "the prospect seemed engaged, so the stated reason must be wrong." That inference is invalid and is the single most common error on this task. Momentum in the transcript is not evidence against any stated reason.' ||

            -- WHAT COUNTS AS EVIDENCE ----------------------------------------
            ' WHAT COUNTS AS EVIDENCE: Do not look only for an explicit "we are not buying because X" statement — that is rare. Instead MINE the transcript for risk, objection, and constraint signals embedded in ordinary discovery talk. Concrete examples of usable evidence:' ||
            '   - Budget/Price: cost pushback, TCO or ROI justification demanded, procurement hurdles, "need to find budget", spend freeze, pricing above their stated range.' ||
            '   - Timing/Early stage: fiscal-year or budget-cycle references, "revisit next quarter", initiative not yet prioritized, no funding allocated, no exec sponsor identified, prerequisite internal work outstanding, only junior stakeholders present.' ||
            '   - Competitive: they already run Spotify/Backstage/Cortex/Harness/OpsLevel, are piloting one, praise one, describe an in-house portal they intend to keep building, OR they are running a formal multi-vendor evaluation / bake-off / vendor comparison. Remember: every deal here is CLOSED-LOST. If the transcript shows the prospect evaluating multiple vendors and the deal is lost, we lost the competition — that IS a competitive loss even if the transcript does not name the winner.' ||
            '   - No value/Product: capability gaps we cannot close, on-prem or air-gap requirements, scepticism that the problem is worth solving, no compelling use case surfaced.' ||
            '   - Fit/Persona: attendee is a consultant, partner, or reseller; company profile far outside our target; asking about a use case we do not serve.' ||
            '   - Sponsorship: champion changing roles, reorganisation, decision-maker never engaged, approval chain unclear.' ||
            '   - Security: unresolved security or compliance review, questionnaire blockers, data-residency constraints.' ||
            ' A clear signal of this kind IS enough to rate yes or no. You do not need a confession.' ||

            -- VERDICT SCALE --------------------------------------------------
            ' VERDICT SCALE — pick exactly one:' ||
            '   yes         = the transcript contains a clear signal corroborating at least one part of the stated reason.' ||
            '   likely_yes  = a signal points toward the stated reason but is weak, indirect, or partially offset by other signals.' ||
            '   likely_no   = signals point toward a DIFFERENT reason than the one stated, but not decisively.' ||
            '   no          = the transcript clearly identifies a different loss driver that NONE of the parts of the stated reason capture. Example: the prospect describes choosing Backstage over Port, while HubSpot says only "Bad timing" — that is a competitive loss the stated reason misses. But if the stated reason were "Product;Competitor", the same transcript would be yes because "Competitor" already captures the Backstage switch. Engagement or momentum alone is NEVER sufficient for no.' ||
            '   unclear     = the transcript contains loss-relevant signals, but they neither corroborate nor displace the stated reason.' ||
            '   unknown     = the transcript contains NO loss-relevant signal at all — pure discovery, demo walkthrough, or logistics, with no objection, constraint, or risk surfaced anywhere. Use this only when there is genuinely nothing to weigh.' ||

            -- CALIBRATION ----------------------------------------------------
            ' CALIBRATION: Commit to yes or no when a signal is clear; reserve likely_yes / likely_no for genuinely weak or conflicting evidence, and unclear for true stalemates. Reserve unknown for signal-free transcripts. Three failure modes to avoid:' ||
            '   (a) rating no because the prospect looked engaged — invalid, see THE CENTRAL PITFALL.' ||
            '   (b) rating unknown because no one said the words "we are not buying" — most transcripts do contain minable signals, so read for objections and constraints before falling back to unknown.' ||
            '   (c) rating no while your own explanation describes evidence that matches the stated reason. A deal where the prospect compared us to Cortex and Cortex won IS a competitive loss — if the stated reason is "Competition", that is yes. A deal where the prospect said Port requires too much effort or lacks a feature IS a product gap — if the stated reason includes "Product" or "Missing Feature", that is yes. If your explanation corroborates the stated reason, the verdict MUST be yes or likely_yes, never no.' ||

            -- TASK -----------------------------------------------------------
            ' YOUR TASK:' ||
            '   1. Mine the transcript for every loss-relevant signal you can find.' ||
            '   2. Compare those signals with the stated HubSpot reason and assign a verdict. A signal can corroborate multiple reason categories simultaneously — e.g. a prospect saying "Cortex just works and Port requires too much building" is evidence for BOTH Competitive AND Product.' ||
            '   3. If the verdict is no, likely_no, or unclear, name the loss driver the transcript actually points to, as a short phrase (e.g. "prefers existing Backstage build", "no budget until next FY", "no executive sponsor engaged"). Leave this empty for yes, likely_yes, and unknown.' ||

            -- OUTPUT ---------------------------------------------------------
            ' OUTPUT — return exactly three fields joined by "|||", nothing else:' ||
            '   <verdict>|||<explanation, 1-3 sentences, quoting or paraphrasing the specific transcript evidence you relied on>|||<actual_loss_driver or empty>' ||
            ' Begin your reply with the verdict word itself (yes, likely_yes, unclear, likely_no, no, or unknown) as the very first characters. No preamble, no reasoning before it, no markdown, no asterisks, no quotation marks, no XML or field labels.' ||

            -- INPUT ----------------------------------------------------------
            ' You will receive up to three inputs: (1) the stated HubSpot closed-lost reason (a structured picklist value) — this is what you are validating, (2) optionally, the rep''s free-text Closed Lost Details — this is evidence, not something to validate. It is written by the rep who owned the deal and often contains context not visible in Gong (e.g. what happened after the last call, emails received, internal decisions communicated offline). Treat it as credible first-party evidence. (3) Gong call transcripts — also evidence. Use BOTH evidence sources together to determine whether the picklist reason is accurate.' ||
            ' STATED HUBSPOT CLOSED_LOST_REASON: "' || ld.CLOSED_LOST_REASON || '".' ||
            IFF(hs.CLOSED_LOST_DETAILS IS NOT NULL AND hs.CLOSED_LOST_DETAILS != '',
                ' REP''S FREE-TEXT CLOSED LOST DETAILS: "' || hs.CLOSED_LOST_DETAILS || '".',
                '') ||
            ' Concatenated Gong Spotlight summary of the last 2-3 calls:\n' || gc.SPOTLIGHT_TEXT
        ) AS AI_RAW
    FROM lost_deals_cat ld
    JOIN gong_classified gc ON gc.SK_DEAL = ld.SK_DEAL
    LEFT JOIN hubspot_closed_lost_details hs ON hs.RECORD_ID = ld.DEAL_CRM_ID::STRING
    WHERE gc.SPOTLIGHT_TEXT IS NOT NULL
),
ai_reason_parsed AS (
    SELECT
        SK_DEAL,
        LOWER(REGEXP_REPLACE(TRIM(SPLIT_PART(AI_RAW, '|||', 1)), '[^a-zA-Z_]', '')) AS AI_REASON_SUPPORTED,
        TRIM(SPLIT_PART(AI_RAW, '|||', 2))         AS AI_REASON_EXPLANATION,
        NULLIF(TRIM(SPLIT_PART(AI_RAW, '|||', 3)), '') AS AI_ALTERNATIVE_REASON
    FROM ai_reason_judgment
),
-- AGENT 2: Reviewer — re-examines "no" and "likely_no" verdicts for self-contradiction
ai_review_judgment AS (
    SELECT
        p.SK_DEAL,
        AI_COMPLETE(
            'claude-4-sonnet',
            'You are a second-pass reviewer auditing a first-pass AI verdict on CRM closed-lost reason accuracy.' ||
            ' The first-pass agent was given a deal''s stated HubSpot closed-lost reason and evidence (Gong call transcripts + optional rep notes), then asked whether the evidence corroborates the stated reason.' ||
            ' The first-pass agent returned a verdict of "' || p.AI_REASON_SUPPORTED || '" with this explanation: "' || p.AI_REASON_EXPLANATION || '"' ||
            IFF(p.AI_ALTERNATIVE_REASON IS NOT NULL, ' and suggested this alternative loss driver: "' || p.AI_ALTERNATIVE_REASON || '".', '.') ||
            ' The stated HubSpot closed-lost reason is: "' || ld.CLOSED_LOST_REASON || '".' ||
            ' YOUR TASK: Check whether the first-pass verdict is SELF-CONSISTENT. Specifically:' ||
            '   1. Does the explanation describe evidence that actually matches the stated reason? If so, the verdict should be yes or likely_yes, not no or likely_no.' ||
            '   2. Is the stated reason multi-part (semicolon-separated)? If so, does the evidence match ANY part? Matching any single part is enough for yes.' ||
            '   3. Key definitions: "Competition" includes multi-vendor evaluations/bake-offs where we lost; vendor names (Backstage, Cortex, Harness, OpsLevel) are competitive signals. "Company cuts" means org-wide financial distress (layoffs, budget cuts, restructuring), distinct from "Budget" (healthy org, price too high). "No value" means prospect sees no value in our solution. "Product" means we lacked a required capability.' ||
            '   4. Remember: every deal is closed-lost. Engagement in the transcript is neutral — do not upgrade a verdict just because the prospect seemed engaged.' ||
            ' OUTPUT — return exactly two fields joined by "|||", nothing else:' ||
            '   <final_verdict>|||<one sentence explaining whether you agree or why you changed it>' ||
            ' The final_verdict must be one of: yes, likely_yes, likely_no, no, unclear, unknown.' ||
            ' If the first-pass verdict is correct, return it unchanged. Only change it if the explanation contradicts the verdict.' ||
            ' Begin your reply with the verdict word itself as the very first characters. No preamble, no markdown.'
        ) AS REVIEW_RAW
    FROM ai_reason_parsed p
    JOIN lost_deals_cat ld ON ld.SK_DEAL = p.SK_DEAL
    WHERE p.AI_REASON_SUPPORTED IN ('no', 'likely_no')
),
ai_review_parsed AS (
    SELECT
        SK_DEAL,
        LOWER(REGEXP_REPLACE(TRIM(SPLIT_PART(REVIEW_RAW, '|||', 1)), '[^a-zA-Z_]', '')) AS REVIEWED_VERDICT,
        TRIM(SPLIT_PART(REVIEW_RAW, '|||', 2)) AS REVIEW_EXPLANATION
    FROM ai_review_judgment
)
SELECT
    ld.SK_DEAL,
    ld.DEAL_CRM_ID,
    ld.DEAL_NAME,
    ld.COMPANY_NAME,
    ld.PIPELINE,
    ld.DEAL_TYPE,
    ld.DEAL_TEAM_NAME,
    ld.DEAL_STAGE,
    ld.DEAL_CLOSED_DATE,
    ld.DEAL_CREATED_DATE,
    ld.SALES_CYCLE_DAYS,
    ld.DEAL_TOTAL_ARR,
    ld.DEAL_NET_NEW_ARR,
    ld.SALES_OWNER,
    ld.CLOSED_LOST_REASON,
    ld.HS_LOST_CATEGORIES,
    gc.CALLS_ANALYZED,
    gc.LATEST_CALL_DATE,
    gc.EARLIEST_ANALYZED_CALL_DATE,
    gc.ANALYZED_SK_CONVERSATIONS,
    gc.GONG_LOST_CATEGORY,
    IFF(gc.GONG_LOST_CATEGORY IS NULL, NULL,
        ARRAYS_OVERLAP(
            gc.GONG_LOST_CATEGORY,
            IFF(ARRAY_SIZE(ld.HS_LOST_CATEGORIES) = 0,
                ARRAY_CONSTRUCT('Other'),
                ld.HS_LOST_CATEGORIES)
        )) AS CATEGORY_MATCH,
    COALESCE(r.REVIEWED_VERDICT, j.AI_REASON_SUPPORTED) AS AI_REASON_SUPPORTED,
    j.AI_REASON_EXPLANATION,
    j.AI_ALTERNATIVE_REASON
FROM lost_deals_cat ld
LEFT JOIN gong_classified gc ON gc.SK_DEAL = ld.SK_DEAL
LEFT JOIN ai_reason_parsed j ON j.SK_DEAL = ld.SK_DEAL
LEFT JOIN ai_review_parsed r ON r.SK_DEAL = ld.SK_DEAL
WHERE COALESCE(gc.CALLS_ANALYZED, 0) > 0
ORDER BY ld.DEAL_CLOSED_DATE DESC;