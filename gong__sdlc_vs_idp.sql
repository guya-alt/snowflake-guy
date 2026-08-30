WITH qualifying_deals AS (
    SELECT SK_DEAL, DEAL_CRM_ID, DEAL_NAME, SK_COMPANY, SK_SALES_OWNER,
           IS_WON, DEAL_TOTAL_ARR, DEAL_TYPE, QUALIFIED_DATE, DEAL_STAGE
    FROM PORT_ANALYTICS_PROD.DWH.FACT_DEALS
    WHERE 1=1 --IS_CLOSED = TRUE
     --  AND DEAL_TYPE = 'newbusiness'
     --  AND PIPELINE = 'Classic'
     --  AND QUALIFIED_DATE IS NOT NULL
),
call_deal AS (
    SELECT
        fc.SK_CONVERSATION,
        fc.CONVERSATION_ID,
        fc.TITLE AS call_title,
        fc.EFFECTIVE_START_DATETIME,
        d.VALUE::STRING AS sk_deal
    FROM PORT_ANALYTICS_PROD.DWH.FACT_CALL fc,
    LATERAL FLATTEN(input => fc.ASSOCIATED_DEAL, OUTER => TRUE) d
    WHERE fc.DURATION_SECONDS >= 600
      AND fc.EFFECTIVE_START_DATETIME >= '2026-08-05'
),
transcript_flags AS (
    SELECT
        ftc.SK_CONVERSATION,
        -- Competitors
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%harness%','%backstage%','%spotify%','%opslevel%','%ops level%','%cortex%','%cortex internal developer%')
             THEN 1 ELSE 0 END) AS competitor_mentioned_flag,
        ARRAY_TO_STRING(ARRAY_COMPACT(ARRAY_CONSTRUCT(
            CASE WHEN MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%backstage%','%spotify%') THEN 1 ELSE 0 END) = 1 THEN 'Backstage' END,
            CASE WHEN MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE '%harness%' THEN 1 ELSE 0 END) = 1 THEN 'Harness' END,
            CASE WHEN MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%opslevel%','%ops level%') THEN 1 ELSE 0 END) = 1 THEN 'OpsLevel' END,
            CASE WHEN MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%cortex%','%cortex internal developer%') THEN 1 ELSE 0 END) = 1 THEN 'Cortex' END
        )), ', ') AS competitors_mentioned,

        -- === IDP pillars ===
        -- 1. Context Lake
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%context lake%','%knowledge graph%','%mcp%','%unified data%','%data model%','%aggregat%data%','%knowledge base%','%second brain%','%organizational knowledge%','%single source of truth%','%graphrag%')
             THEN 1 ELSE 0 END) AS context_lake,
        -- 2. Software Catalog
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%software catalog%','%service catalog%','%single pane of glass%','%dependency map%','%catalog page%','%blueprint%','%entity%','%entities%','%אנטיטי%','%קטלוג%','%בלופרינט%','%בלו פרינט%','%developer portal%','%dev portal%','%visibility%','%inventory of service%','%microservice%','%service owner%','%service map%','%tech stack%','%connector registry%','%catalog table%')
             THEN 1 ELSE 0 END) AS software_catalog,
        -- 3. Actions
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%self-service action%','%self service action%','%day-two operation%','%day two operation%','%day-1%','%day one%','%approval flow%','%self service portal%','%scaffolding a service%','%scaffold%','%create a service%','%provision%request%','%trigger%action%','%action%trigger%','%developer onboard%','%onboard%developer%','%service template%','%github action%','%adoption flow%','%adopt%best practice%')
             THEN 1 ELSE 0 END) AS actions,
        -- 4. AI Agents
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%skill registry%','%skills registry%','%agent registry%','%prompt registry%','%mcp catalog%','%mcp server%','%manage skills%','%byollm%','%bring your own llm%','%agent%governance%','%agents are being managed%','%port mcp%','%skill compliance%','%skill%','%ai agent%','%agent%autonomous%','%port agent%','%agentic platform%','%copilot%','%llm%','%genai%','%gen ai%','%agentic tooling%','%port ai%','%skill adoption%','%agentic engineering%','%agentic chaos%','%human in the loop%','%human in a loop%','%cloud code%','%ai coding%')
             THEN 1 ELSE 0 END) AS ai_agents,
        -- 5. Scorecards
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%scorecard%','%סקורקארד%','%maturity score%','%maturity model%','%production readiness%','%production ready%','%golden path%','%paved road%','%guardrail%','%engineering standard%','%best practice%','%compliance%','%readiness check%','%quality gate%','%standard%enforce%','%sla%','%slo%','%campaign%','%maturity level%','%compliant%','%renovate%','%dependabot%','%governance gap%')
             THEN 1 ELSE 0 END) AS scorecards,
        -- 6. Workflow Orchestrator
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%workflow orchestrat%','%workflow builder%','%automation workflow%','%port workflow%','%runbook%','%reusable workflow%','%workflow management%','%automation builder%','%workflow%automat%','%וורקפלו%','%אוטומציה%','%chaining%action%','%pipeline%automat%')
             THEN 1 ELSE 0 END) AS workflow_orchestrator,
        -- 7. Interface Designer
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%interface designer%','%interface builder%','%custom view%','%dashboard builder%','%portal page%','%role-based view%','%custom page%','%widget%','%homepage%','%landing page%','%דשבורד%','%dashboard template%','%custom react%','%scope%dashboard%')
             THEN 1 ELSE 0 END) AS interface_designer,
        -- 8. Access Controls
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%access control%','%rbac%','%role-based access%','%permission%','%node level p%','%הרשא%','%team ownership%','%ownership%')
             THEN 1 ELSE 0 END) AS access_controls,
        -- 9. Integrations
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%integration%','%אינטגרציה%','%אינטגריישן%','%ocean framework%','%port ocean%','%data source%','%connector%','%webhook%','%api%connect%','%ingest%data%','%exporter%','%argocd%','%argo cd%','%gitops%','%sonarqube%','%sonar cube%','%datadog%','%data dog%')
             THEN 1 ELSE 0 END) AS integrations,

        -- === SDLC solutions ===
        -- 1. Autonomous Ticket Resolution
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%autonomous ticket%','%ticket resolution%','%auto-triage%','%auto triage%','%ticket backlog%','%coding agent%','%auto-fix%','%triage bug%','%resolve tickets%','%jira%automat%','%servicenow%automat%','%ticket%agent%','%ticket to pr%','%ticket to production%','%bug to pr%','%auto-resolve%','%auto resolve%','%raise a pr%','%raise%pull request%')
             THEN 1 ELSE 0 END) AS autonomous_ticket_resolution,
        -- 2. Self-Healing Incidents
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%self-healing%','%self healing%','%mttr%','%mean time%','%incident resolut%','%incident triage%','%auto-remediat%','%autonomous incident%','%on-call burnout%','%on call%pagerduty%','%pagerduty%on call%','%incident healing%','%vulnerability remediation%','%vulnerability management%','%incident%automat%','%pagerduty%','%opsgenie%','%אינסידנט%','%אינסדנט%','%incident%response%','%rollback%','%cve%','%blast radius%','%root cause analysis%','%snyk%vulnerabilit%','%triage%issue%')
             THEN 1 ELSE 0 END) AS self_healing_incidents,
        -- 3. Engineering Intelligence
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%engineering intelligence%','%dora metric%','%dora%','%engineering metric%','%deployment frequency%','%lead time for change%','%change fail%','%developer experience%','%developer productivity%','%engineering velocity%','%cycle time%','%ai adoption%','%measure%engineer%','%engineering kpi%','%dev%metric%','%devex%','%engineering health%','%pull request%time%','%pr%cycle%','%space metric%','%sdlc%metric%')
             THEN 1 ELSE 0 END) AS engineering_intelligence,
        -- 4. Resource Management
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%resource management%','%environment provision%','%infrastructure provision%','%provisioning cloud%','%cloud cost%','%manual provisioning%','%developer environment%','%spin up%','%terraform%','%infrastructure as code%','%cloud resource%','%ephemeral environment%','%pulumi%','%crossplane%','%finops%','%fin ops%','%namespace%provision%','%kubernetes%provision%','%k8s%provision%')
             THEN 1 ELSE 0 END) AS resource_management,
        -- 5. Agentic Work Management
        MAX(CASE WHEN ftc.TRANSCRIPT_CHAPTER_WINDOW ILIKE ANY ('%agentic work management%','%work management%','%daily view%','%plan my day%','%context switching%','%fragmented dashboard%','%developer toil%','%reduce toil%','%engineering time%manual%','%cognitive load%','%too many tools%','%tool sprawl%','%backlog%priorit%','%priorit%task%','%task%priorit%','%developer hub%','%dev hub%')
             THEN 1 ELSE 0 END) AS agentic_work_management
    FROM PORT_ANALYTICS_PROD.DWH.FACT_TRANSCRIPT_CHAPTER ftc
    WHERE ftc.SK_CONVERSATION IN (SELECT SK_CONVERSATION FROM call_deal)
    GROUP BY 1
),
-- Transcript snippets for ALL conversations (no prefilter)
call_snippets AS (
    SELECT
        ftc.SK_CONVERSATION,
        LISTAGG(LEFT(ftc.TRANSCRIPT_CHAPTER_WINDOW, 150), '\n')
            WITHIN GROUP (ORDER BY ftc.CONVERSATION_ORDER_POSITION) AS full_transcript_sample
    FROM PORT_ANALYTICS_PROD.DWH.FACT_TRANSCRIPT_CHAPTER ftc
    WHERE ftc.SK_CONVERSATION IN (SELECT SK_CONVERSATION FROM call_deal)
    GROUP BY 1
),
-- AI classification: runs on ALL conversations, uses full transcript sample
ai_verification AS (
    SELECT
        cs.SK_CONVERSATION,
        TRY_PARSE_JSON(
            REGEXP_REPLACE(
                SNOWFLAKE.CORTEX.COMPLETE('mistral-large2',
                    'You are an IDP/SDLC Topic Scorer for Port, an Internal Developer Platform (also called Agentic Engineering Platform). '
                    || 'Analyze the following sales call transcript and determine which topics were discussed. '
                    || 'The transcript may be in Hebrew or English.\n\n'
                    || '=== SCORING RULES ===\n'
                    || '- Be GENEROUS: if the topic was mentioned even briefly or tangentially, score true\n'
                    || '- Port employees often demo features, explain capabilities, or ask discovery questions\n'
                    || '- Customer mentioning a pain point that maps to a category = true\n'
                    || '- Port team showing or explaining a feature in that category = true\n'
                    || '- Only score false if clearly NOT discussed at all\n\n'
                    || '=== IDP PILLARS (Platform backbone capabilities) ===\n'
                    || '- context_lake: Data aggregation layer — Context Lake, knowledge graph, MCP as data interface, unified data model, connecting data sources into one place\n'
                    || '- software_catalog: Service/software catalog, single pane of glass, dependency mapping, catalog pages, entities, blueprints, developer portal, visibility into services/resources\n'
                    || '- actions: Self-service actions, day-1/day-2 operations, scaffolding services, approval flows, developer portal actions, triggering workflows from the catalog\n'
                    || '- ai_agents: AI agent governance — skill/agent/prompt registries, MCP servers, managing AI skills, BYOLLM, agent compliance, Port skills\n'
                    || '- scorecards: Scorecards, maturity/readiness scores, golden paths, guardrails, engineering standards, best practices, compliance tracking, quality gates\n'
                    || '- workflow_orchestrator: Workflow orchestration, automation builders, runbooks, reusable workflows, chaining actions together\n'
                    || '- interface_designer: Custom portal pages, interface/dashboard builders, role-based views, widgets, homepage customization\n'
                    || '- access_controls: RBAC, permissions, role-based access, node-level permissions, team ownership, who can see/do what\n'
                    || '- integrations: Integrations with external tools, Ocean framework, data sources, connectors, webhooks, API connections\n\n'
                    || '=== SDLC SOLUTIONS (Agentic autonomous workflows) ===\n'
                    || '- autonomous_ticket_resolution: Agent auto-triages/resolves tickets (Jira, ServiceNow), coding agents, auto-fix, backlog reduction\n'
                    || '- self_healing_incidents: Agent detects and remediates incidents, MTTR reduction, on-call burnout, PagerDuty/OpsGenie integration, vulnerability management, auto-remediation\n'
                    || '- engineering_intelligence: DORA metrics, engineering metrics, developer productivity measurement, cycle time, deployment frequency, AI adoption tracking\n'
                    || '- resource_management: Autonomous environment/infrastructure provisioning, cloud cost management, developer environments, Terraform, spin-up automation\n'
                    || '- agentic_work_management: Developer work management, daily planning, context switching reduction, developer toil reduction, cognitive load, tool sprawl\n\n'
                    || '=== COMPETITORS ===\n'
                    || 'If any of these were mentioned, return their names in a "competitors" array: Backstage, Harness, OpsLevel, Cortex\n\n'
                    || '=== TRANSCRIPT ===\n'
                    || LEFT(cs.full_transcript_sample, 6000) || '\n\n'
                    || '=== OUTPUT ===\n'
                    || 'Output RAW JSON only. No markdown, no code fences, no backticks. Keys: context_lake, software_catalog, actions, ai_agents, scorecards, workflow_orchestrator, interface_designer, access_controls, integrations, autonomous_ticket_resolution, self_healing_incidents, engineering_intelligence, resource_management, agentic_work_management, competitors. Values: true/false for each (competitors is an array of strings or empty array).'
                ),
                '```json|```', ''
            )
        ) AS ai_result
    FROM call_snippets cs
    WHERE cs.SK_CONVERSATION IN (
        SELECT SK_CONVERSATION FROM transcript_flags
        WHERE context_lake = 1
           OR software_catalog = 1
           OR actions = 1
           OR ai_agents = 1
           OR scorecards = 1
           OR workflow_orchestrator = 1
           OR interface_designer = 1
           OR access_controls = 1
           OR integrations = 1
           OR autonomous_ticket_resolution = 1
           OR self_healing_incidents = 1
           OR engineering_intelligence = 1
           OR resource_management = 1
           OR agentic_work_management = 1
    )
)
SELECT
    cd.CONVERSATION_ID AS gong_id,
    cd.call_title,
    cd.EFFECTIVE_START_DATETIME::DATE AS call_date,
    fd.DEAL_CRM_ID AS deal_id,
    fd.DEAL_NAME,
    fd.SK_COMPANY AS company_id,
    c.COMPANY_NAME,
    ROW_NUMBER() OVER (PARTITION BY cd.sk_deal ORDER BY cd.EFFECTIVE_START_DATETIME) AS call_sequence,
    e.DISPLAY_NAME AS owner,
    tf.competitors_mentioned,
    fd.DEAL_TYPE,
    -- AI-verified flags (only when keyword flag = 1)
    CASE WHEN tf.context_lake = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:context_lake::STRING), TRY_TO_BOOLEAN(ac.ai_result:context_lake:confirmed::STRING))
    END AS ai_context_lake,
    CASE WHEN tf.software_catalog = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:software_catalog::STRING), TRY_TO_BOOLEAN(ac.ai_result:software_catalog:confirmed::STRING))
    END AS ai_software_catalog,
    CASE WHEN tf.actions = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:actions::STRING), TRY_TO_BOOLEAN(ac.ai_result:actions:confirmed::STRING))
    END AS ai_actions,
    CASE WHEN tf.ai_agents = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:ai_agents::STRING), TRY_TO_BOOLEAN(ac.ai_result:ai_agents:confirmed::STRING))
    END AS ai_ai_agents,
    CASE WHEN tf.scorecards = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:scorecards::STRING), TRY_TO_BOOLEAN(ac.ai_result:scorecards:confirmed::STRING))
    END AS ai_scorecards,
    CASE WHEN tf.workflow_orchestrator = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:workflow_orchestrator::STRING), TRY_TO_BOOLEAN(ac.ai_result:workflow_orchestrator:confirmed::STRING))
    END AS ai_workflow_orchestrator,
    CASE WHEN tf.interface_designer = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:interface_designer::STRING), TRY_TO_BOOLEAN(ac.ai_result:interface_designer:confirmed::STRING))
    END AS ai_interface_designer,
    CASE WHEN tf.access_controls = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:access_controls::STRING), TRY_TO_BOOLEAN(ac.ai_result:access_controls:confirmed::STRING))
    END AS ai_access_controls,
    CASE WHEN tf.integrations = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:integrations::STRING), TRY_TO_BOOLEAN(ac.ai_result:integrations:confirmed::STRING))
    END AS ai_integrations,
    CASE WHEN tf.autonomous_ticket_resolution = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:autonomous_ticket_resolution::STRING), TRY_TO_BOOLEAN(ac.ai_result:autonomous_ticket_resolution:confirmed::STRING))
    END AS ai_autonomous_ticket_resolution,
    CASE WHEN tf.self_healing_incidents = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:self_healing_incidents::STRING), TRY_TO_BOOLEAN(ac.ai_result:self_healing_incidents:confirmed::STRING))
    END AS ai_self_healing_incidents,
    CASE WHEN tf.engineering_intelligence = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:engineering_intelligence::STRING), TRY_TO_BOOLEAN(ac.ai_result:engineering_intelligence:confirmed::STRING))
    END AS ai_engineering_intelligence,
    CASE WHEN tf.resource_management = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:resource_management::STRING), TRY_TO_BOOLEAN(ac.ai_result:resource_management:confirmed::STRING))
    END AS ai_resource_management,
    CASE WHEN tf.agentic_work_management = 1
         THEN COALESCE(TRY_TO_BOOLEAN(ac.ai_result:agentic_work_management::STRING), TRY_TO_BOOLEAN(ac.ai_result:agentic_work_management:confirmed::STRING))
    END AS ai_agentic_work_management,
    ac.ai_result:competitors::STRING AS ai_competitors,
    -- IDP pillar flags
    tf.context_lake,
    tf.software_catalog,
    tf.actions,
    tf.ai_agents,
    tf.scorecards,
    tf.workflow_orchestrator,
    tf.interface_designer,
    tf.access_controls,
    tf.integrations,
    -- SDLC solution flags
    tf.autonomous_ticket_resolution,
    tf.self_healing_incidents,
    tf.engineering_intelligence,
    tf.resource_management,
    tf.agentic_work_management,
    -- Scores
    (tf.context_lake + tf.software_catalog + tf.actions + tf.ai_agents
     + tf.scorecards + tf.workflow_orchestrator + tf.interface_designer
     + tf.access_controls + tf.integrations) / 9.0 AS idp_score,
    (tf.autonomous_ticket_resolution + tf.self_healing_incidents
     + tf.engineering_intelligence + tf.resource_management
     + tf.agentic_work_management) / 5.0 AS sdlc_score
FROM call_deal cd
LEFT JOIN qualifying_deals fd ON cd.sk_deal = fd.SK_DEAL
LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_EMPLOYEE e ON fd.SK_SALES_OWNER = e.SK_EMPLOYEE
LEFT JOIN PORT_ANALYTICS_PROD.DWH.DIM_COMPANY c
    ON fd.SK_COMPANY = c.SK_COMPANY
   AND COALESCE(c.COMPANY_NAME, '') NOT ILIKE '%test%'
   AND COALESCE(c.COMPANY_NAME, '') != 'Port'
   AND c._IS_DELETED = FALSE
   AND c.ARCHIVED = FALSE
LEFT JOIN transcript_flags tf ON cd.SK_CONVERSATION = tf.SK_CONVERSATION
LEFT JOIN ai_verification ac ON cd.SK_CONVERSATION = ac.SK_CONVERSATION
ORDER BY cd.EFFECTIVE_START_DATETIME DESC, call_sequence
limit 500
;
