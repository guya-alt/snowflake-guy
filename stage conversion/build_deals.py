"""
HubSpot Deals Structured Framework
Loads HubSpot deal exports, validates with Pydantic, and produces Pandas DataFrames.
"""

import json
import glob
import os
from datetime import datetime
from typing import Optional

import pandas as pd
from pydantic import BaseModel, Field, field_validator

# ─── LOOKUPS ────────────────────────────────────────────────────────────────────

PIPELINES = {
    "default": "Classic",
    "69442853": "Renewals",
}

DEAL_STAGES = {
    # Classic pipeline
    "982622489": ("SDR Discovery", "Classic"),
    "65800978": ("SDR / Omitted Opp", "Classic"),
    "65800980": ("Demo / Presentation", "Classic"),
    "65537604": ("Business Validation", "Classic"),
    "22339760": ("Formal Pilot", "Classic"),
    "contractsent": ("Business Case Confirmation", "Classic"),
    "65537605": ("Negotiation / Legal", "Classic"),
    "closedwon": ("Closed Won", "Classic"),
    "closedlost": ("Closed Lost", "Classic"),
    # Renewals pipeline
    "134696621": ("Upcoming", "Renewals"),
    "134696622": ("Reconnect", "Renewals"),
    "134696623": ("In Progress", "Renewals"),
    "134696624": ("Negotiation", "Renewals"),
    "134696626": ("Closed Won", "Renewals"),
    "134696627": ("Churn", "Renewals"),
}

TEAMS = {
    "56771934": "US MM",
    "56771961": "US Ent",
    "56771970": "EMEA Ent",
    "56771974": "APJ",
    "59993671": "EMEA MM",
    "60317762": "AM",
    "76440130": "LATAM",
    "64886205": "Exec",
    "56658847": "TSM",
    "74018470": "TSM-EMEA APJ",
    "74018489": "TSM-US",
    "35880189": "Sales",
    "35880194": "SDR",
    "85439242": "SDR US",
    "85439411": "SDR EMEA",
    "78214122": "Channel",
    "82720747": "Solutions Architects",
    "56768107": "Ops",
}

OWNERS = {
    "50368369": "Svet Slizskaya",
    "60448518": "Kemin Kasundra",
    "61839613": "Chiranjeev Singh",
    "65219295": "Aaron Taylor",
    "69367561": "Noa Sarid",
    "75412512": "Daniel Alper",
    "75654910": "Omri Negri",
    "75854050": "Roy Waxman",
    "75971976": "Magali Philippe",
    "75992385": "Gus Stewart",
    "75992509": "Zac Law",
    "75999210": "Jill Countey",
    "76099802": "Kevin Tarbell",
    "76125093": "Yael Oren",
    "76784826": "Adi Weinstock",
    "77427269": "Charity Lee",
    "77469083": "Maya Margalit",
    "77581812": "Jason Chiu",
    "77773085": "Todd Rizley",
    "77888140": "Omri Gez",
    "78296838": "Adrian Wong",
    "78352892": "Stevan Vanderwerf",
    "78373955": "Antara Palit",
    "78565039": "Tali Cohen",
    "78599755": "Digital Success",
    "78642514": "Or Fattal",
    "78819457": "James Bennett",
    "78914750": "Subby Makinde",
    "78945858": "Lior-Naim Alon",
    "79046476": "Amir Shmulevich",
    "79089197": "Chris Hodson",
    "79222175": "Christos Lemos",
    "79268053": "Eric Fernandez",
    "79358048": "James Pritchard",
    "79698308": "Kristen Collins",
    "79727038": "Adrian Sandu",
    "80061225": "Travis Dadoly",
    "80097359": "Cameron Kayfish",
    "80372643": "Lee Silberstein",
    "80589734": "Idit Matas",
    "81123048": "Jesleen Jose",
    "81434377": "Anna Persico",
    "81434378": "Priya Raghu",
    "81434379": "Dhananjai Govind",
    "81434381": "Oladipupo Ibeun",
    "81652323": "Uday Korlimarla",
    "81755263": "Bill Gilleran",
    "82147241": "Raz Chen",
    "82177445": "EJ Rauseo",
    "82504222": "Al Sharma",
    "82748400": "Mariela Moreno",
    "83006139": "Lisa Harshman",
    "83467280": "Nathan Roys",
    "83698217": "Animesh Mishra",
    "83705563": "Sam Bettencourt",
    "83876062": "German Martinez",
    "83876128": "Nora O'Keeffe",
    "83980848": "Chris Sweeney",
    "84280460": "Ariel Sakin",
    "84282286": "Haim Natan",
    "84321485": "Jeff Richards",
    "84331751": "Gal Katz",
    "84362691": "Kavita Pant",
    "84749268": "Guy Friedman",
    "84996372": "Claudia Epsha",
    "85302746": "Dustin Link",
    "85389865": "Etay Alony",
    "85810496": "Bryan Nairn",
    "86812399": "John Barnes",
    "87061848": "Matt Bilsland",
    "87080824": "Ignacio De Loera",
    "87124846": "Daniela Levy",
    "87239511": "Guy Steinberger",
    "87355626": "Edouard Carakehian",
    "87364427": "Jenny Lucas",
    "87371216": "Thomas Donohue",
    "87431209": "Daniel Chupak",
    "87536317": "Rick Walker",
    "87631769": "Evan Smith",
    "88038053": "Aaron Marans",
    "88038137": "Wren Huston",
    "88099756": "Rick Bruneau",
    "88200364": "Matan Alon",
    "88726691": "Alon Flaxer",
    "88827235": "David Gray",
    "89004780": "Chris Warden",
    "89035526": "Jamie Summers",
    "89035573": "James Butcher",
    "89043609": "James Butcher",
    "89392376": "Damian Chelverajan",
    "89643596": "Rocio Sasson",
    "89684495": "Dana Sela Wulich",
    "89738312": "Ingrid Attal",
    "89894958": "Victoria Shatkin",
    "89985716": "Mohammed Shariff",
    "90037962": "Rachel Jean",
    "90564619": "Corey Wu",
    "90564951": "Andrew Johnston",
    "90831521": "Aaron Regis",
    "90931408": "Catarina Fisher",
    "90972177": "Yaniv Ninyo",
    "91175878": "Aman Alung",
    "91462130": "Guy Hanegby",
    "91471963": "Paula Schaefer",
    "91767097": "PortIT Integration",
    "91895308": "Claudia Epsha",
    "91895309": "Svet S Nomad",
    "92288168": "HubSpot Integration",
    "92630915": "Aviv Stern",
    "92701057": "Guy Amitai",
    "92701237": "Guy Amitai",
    "93313402": "Cecilia Santis",
    "93618480": "Samdeep Kohli",
    "93898475": "Nir Poleg",
    "93946999": "David McInerny",
    "94059199": "Chukwuemeka Nwaoma",
    "94364292": "Michael Armah",
    "94364298": "Iyanuoluwa Adebayo",
    "94449930": "Luis Martinez",
    "94504824": "Guy Shtuden",
    "95591687": "Nir Zalmanovich",
    "95916435": "Jordan Aspis",
    "96380859": "Simon Elliott",
    "96955526": "Maria Kofler",
    "97298546": "Port GTM",
    "136577623": "Royi Podhorzer",
    "146492446": "Logan Loisel",
    "178480005": "Omer Dahan",
    "193013249": "Zohar Einy",
    "196176490": "Matan Gubkin",
    "202316722": "Dana Salman",
    "208917870": "Roni Floman",
    "214250678": "Keren Shenhav",
    "214250679": "Gil Ben-Horin",
    "214262884": "Ella Politis",
    "218234452": "Harel Panker",
    "218622006": "Ella Furman",
    "222087247": "Yonatan Boguslavski",
    "223556780": "Lorien Balofsky",
    "230158773": "Dudi Elhadad",
    "231010113": "Tomer Shvadron",
    "252675251": "Dylan Leija",
    "255332108": "Zohar Einy",
    "282799381": "Noga Furman",
    "308969732": "Eden Elhadad",
    "310498833": "Yonatan Boguslavski",
    "311974356": "Johana Ochoa",
    "343546672": "Tom Skarzynski",
    "357554018": "John Romano",
    "366471813": "Yonatan Boguslavski",
    "385648749": "Suzanne Daniels",
    "423067495": "Aviv Lavie",
    "434077726": "William Nagle",
    "440613638": "Scott Dunion",
    "445242967": "Mor Paz",
    "473746346": "Omri Gilad",
    "488175233": "Shlomi Cohen",
    "488269885": "Matar Peles",
    "510878318": "Tom Tankilevitch",
    "515675218": "Dan Amzulescu",
    "527007754": "Amit Zonenfeld",
    "528508753": "Val Burtakov",
    "533723988": "Anuj Singh",
    "533796879": "Hadar Cohen",
    "543417960": "Chris Newsome",
    "543417961": "Sam Neill",
    "549220980": "Maria Lepp",
    "550986714": "Chase Depperschmidt",
    "556811281": "Netta Borowitsh",
    "569957424": "Port RR",
    "603113359": "Jonathan Gruber",
    "617174095": "Benjamin Duckworth",
    "618729487": "Keren Aisman",
    "628258418": "Yair Siman Tov",
    "634232641": "Jenny Salem",
    "637030154": "Sooraj Shah",
    "643061137": "Gal Tarrab Levi",
    "646598841": "Sales OPS",
    "646604656": "Cillian Golden",
    "648023618": "Amit Zonenfeld",
    "679474689": "Aidan O'Connor",
    "679474690": "Donald Scott",
    "683641506": "Roy Naar",
    "687228428": "Jim Smith",
    "689956614": "Roy Naar",
    "691230031": "Gur Shafriri",
    "740714164": "Bar Itzkovich",
    "804688078": "Ozz Shafriri",
    "807864695": "Hila Kashai",
    "858627600": "Jenna Danoy",
    "943085518": "Daniel Alper",
    "1009211010": "Yarden Holtzer",
    "1038004649": "Grant Dienaar",
    "1059862275": "Rao Komar",
    "1311943143": "Aviv Teldan",
    "1335191011": "Sebastien Blanc",
    "1364303646": "Ross Geall",
    "1495461488": "Elliott Spira",
    "1498256862": "Daniel Hatcher",
    "1556266598": "Dana Salman",
    "1586222138": "Roi Talpaz",
    "1611348791": "Jeff Graham",
    "1640663165": "Matan Grady",
    "1670032284": "Bri Strozewski",
    "1703234620": "Danny Hatcher",
    "1716326684": "Ory Casper",
    "1734082054": "Joe Leland",
    "1849256429": "Roni Amar",
    "2053646447": "Stav Adler",
    "2088680648": "Sharon Peretz",
    "2113492932": "Jim Armstrong",
}

DEAL_TYPES = {
    "newbusiness": "New Business",
    "existingbusiness": "Renewal",
    "Expansion": "Expansion",
}

# Stage ordering for conversion analysis (index = position in funnel)
CLASSIC_STAGE_ORDER = [
    "SDR Discovery",
    "SDR / Omitted Opp",
    "Demo / Presentation",
    "Business Validation",
    "Formal Pilot",
    "Business Case Confirmation",
    "Negotiation / Legal",
    "Closed Won",
]

RENEWALS_STAGE_ORDER = [
    "Upcoming",
    "Reconnect",
    "In Progress",
    "Negotiation (Renewals)",
    "Closed Won (Renewals)",
]

# All stage IDs for timestamp extraction
ALL_STAGE_IDS = list(DEAL_STAGES.keys())


# ─── PYDANTIC MODELS ────────────────────────────────────────────────────────────


class StageTimestamps(BaseModel):
    """Timestamps for when a deal entered each stage."""

    sdr_discovery: Optional[datetime] = None
    sdr_omitted_opp: Optional[datetime] = None
    demo_presentation: Optional[datetime] = None
    business_validation: Optional[datetime] = None
    formal_pilot: Optional[datetime] = None
    business_case_confirmation: Optional[datetime] = None
    negotiation_legal: Optional[datetime] = None
    closed_won: Optional[datetime] = None
    closed_lost: Optional[datetime] = None
    # Renewals
    upcoming: Optional[datetime] = None
    reconnect: Optional[datetime] = None
    in_progress: Optional[datetime] = None
    negotiation_renewals: Optional[datetime] = None
    closed_won_renewals: Optional[datetime] = None
    churn: Optional[datetime] = None

    @classmethod
    def from_properties(cls, props: dict) -> "StageTimestamps":
        stage_id_to_field = {
            "982622489": "sdr_discovery",
            "65800978": "sdr_omitted_opp",
            "65800980": "demo_presentation",
            "65537604": "business_validation",
            "22339760": "formal_pilot",
            "contractsent": "business_case_confirmation",
            "65537605": "negotiation_legal",
            "closedwon": "closed_won",
            "closedlost": "closed_lost",
            "134696621": "upcoming",
            "134696622": "reconnect",
            "134696623": "in_progress",
            "134696624": "negotiation_renewals",
            "134696626": "closed_won_renewals",
            "134696627": "churn",
        }
        data = {}
        for stage_id, field_name in stage_id_to_field.items():
            v2_key = f"hs_v2_date_entered_{stage_id}"
            v1_key = f"hs_date_entered_{stage_id}"
            value = props.get(v2_key)
            if not value:
                value = props.get(v1_key)
            if value:
                data[field_name] = value
        return cls(**data)


class Deal(BaseModel):
    """A single HubSpot deal with decoded fields."""

    id: str
    name: str
    amount: Optional[float] = None
    pipeline_id: str
    pipeline_name: str
    stage_id: str
    stage_name: str
    deal_type_id: Optional[str] = None
    deal_type_name: Optional[str] = None
    owner_id: Optional[str] = None
    owner_name: Optional[str] = None
    team_id: Optional[str] = None
    team_name: Optional[str] = None
    geo: Optional[str] = None
    mega_source: Optional[str] = None
    deal_source: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    qualified_date: Optional[str] = None
    url: str
    stage_timestamps: StageTimestamps

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, v):
        if v is None or v == "":
            return None
        return float(v)

    @classmethod
    def from_raw(cls, raw: dict, owners: dict | None = None) -> "Deal":
        props = raw["properties"]
        pipeline_id = props.get("pipeline", "")
        stage_id = props.get("dealstage", "")
        team_id = props.get("hubspot_team_id")
        deal_type_id = props.get("dealtype")
        owner_id = props.get("hubspot_owner_id")
        owners = owners or {}

        return cls(
            id=str(raw["id"]),
            name=props.get("dealname", ""),
            amount=props.get("amount"),
            pipeline_id=pipeline_id,
            pipeline_name=PIPELINES.get(pipeline_id, pipeline_id),
            stage_id=stage_id,
            stage_name=DEAL_STAGES.get(stage_id, (stage_id, ""))[0],
            deal_type_id=deal_type_id,
            deal_type_name=DEAL_TYPES.get(deal_type_id, deal_type_id) if deal_type_id else None,
            owner_id=owner_id,
            owner_name=owners.get(owner_id, owner_id) if owner_id else None,
            team_id=team_id,
            team_name=TEAMS.get(team_id, team_id) if team_id else None,
            geo=props.get("geography") or None,
            mega_source=props.get("mega_source") or None,
            deal_source=props.get("deal_source") or None,
            created_at=raw.get("createdAt") or props.get("createdate", ""),
            updated_at=raw.get("updatedAt") or props.get("hs_lastmodifieddate", ""),
            qualified_date=props.get("qualified_date"),
            url=raw.get("url", ""),
            stage_timestamps=StageTimestamps.from_properties(props),
        )


# ─── LOADING ────────────────────────────────────────────────────────────────────


def load_json_files(folder: str) -> list[Deal]:
    """Load all response*.json files from the folder."""
    pattern = os.path.join(folder, "response*.json")
    files = glob.glob(pattern)
    deals = []
    for filepath in files:
        with open(filepath, "r") as f:
            data = json.load(f)
        for raw_deal in data.get("results", []):
            deals.append(Deal.from_raw(raw_deal))
    print(f"Loaded {len(deals)} deal records from {len(files)} files")
    return deals


def deduplicate(deals: list[Deal]) -> list[Deal]:
    """Deduplicate by deal ID, keeping the most recently updated version."""
    seen: dict[str, Deal] = {}
    for deal in deals:
        if deal.id not in seen or deal.updated_at > seen[deal.id].updated_at:
            seen[deal.id] = deal
    deduped = list(seen.values())
    print(f"Deduplicated to {len(deduped)} unique deals")
    return deduped


# ─── DATAFRAME BUILDERS ─────────────────────────────────────────────────────────


def deals_to_dataframe(deals: list[Deal]) -> pd.DataFrame:
    """Convert deals to a flat DataFrame with decoded fields."""
    rows = []
    for d in deals:
        rows.append({
            "deal_id": d.id,
            "deal_name": d.name,
            "amount": d.amount,
            "pipeline": d.pipeline_name,
            "stage": d.stage_name,
            "deal_type": d.deal_type_name,
            "owner": d.owner_name,
            "team": d.team_name,
            "geo": d.geo,
            "mega_source": d.mega_source,
            "deal_source": d.deal_source,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
            "qualified_date": d.qualified_date,
            "url": d.url,
        })
    df = pd.DataFrame(rows)
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
    df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True)
    df["qualified_date"] = pd.to_datetime(df["qualified_date"], errors="coerce")
    return df


def stage_timestamps_dataframe(deals: list[Deal]) -> pd.DataFrame:
    """Wide-format DataFrame: one row per deal, one column per stage entry timestamp."""
    rows = []
    for d in deals:
        row = {"deal_id": d.id, "pipeline": d.pipeline_name}
        ts = d.stage_timestamps
        row["SDR Discovery"] = ts.sdr_discovery
        row["SDR / Omitted Opp"] = ts.sdr_omitted_opp
        row["Demo / Presentation"] = ts.demo_presentation
        row["Business Validation"] = ts.business_validation
        row["Formal Pilot"] = ts.formal_pilot
        row["Business Case Confirmation"] = ts.business_case_confirmation
        row["Negotiation / Legal"] = ts.negotiation_legal
        row["Closed Won"] = ts.closed_won
        row["Closed Lost"] = ts.closed_lost
        row["Upcoming"] = ts.upcoming
        row["Reconnect"] = ts.reconnect
        row["In Progress"] = ts.in_progress
        row["Negotiation (Renewals)"] = ts.negotiation_renewals
        row["Closed Won (Renewals)"] = ts.closed_won_renewals
        row["Churn"] = ts.churn
        rows.append(row)
    df = pd.DataFrame(rows)
    # Convert all timestamp columns to datetime
    ts_cols = [c for c in df.columns if c not in ("deal_id", "pipeline")]
    for col in ts_cols:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
    return df


# ─── ANALYSIS HELPERS ───────────────────────────────────────────────────────────


def stage_conversion_rates(ts_df: pd.DataFrame, pipeline: str = "Classic") -> pd.DataFrame:
    """Calculate stage-to-stage conversion rates for a pipeline."""
    if pipeline == "Classic":
        stages = CLASSIC_STAGE_ORDER
    else:
        stages = RENEWALS_STAGE_ORDER

    pdf = ts_df[ts_df["pipeline"] == pipeline]
    results = []
    for i, stage in enumerate(stages):
        entered = pdf[stage].notna().sum()
        if i == 0:
            conv_rate = None
            from_stage = None
        else:
            prev_entered = pdf[stages[i - 1]].notna().sum()
            conv_rate = entered / prev_entered if prev_entered > 0 else None
            from_stage = stages[i - 1]
        results.append({
            "stage": stage,
            "from_stage": from_stage,
            "deals_entered": entered,
            "conversion_rate": conv_rate,
        })
    return pd.DataFrame(results)


def time_in_stage(ts_df: pd.DataFrame, pipeline: str = "Classic") -> pd.DataFrame:
    """Calculate median days between consecutive stages."""
    if pipeline == "Classic":
        stages = CLASSIC_STAGE_ORDER
    else:
        stages = RENEWALS_STAGE_ORDER

    pdf = ts_df[ts_df["pipeline"] == pipeline]
    results = []
    for i in range(len(stages) - 1):
        from_stage = stages[i]
        to_stage = stages[i + 1]
        mask = pdf[from_stage].notna() & pdf[to_stage].notna()
        if mask.sum() > 0:
            deltas = (pdf.loc[mask, to_stage] - pdf.loc[mask, from_stage]).dt.total_seconds() / 86400
            median_days = deltas.median()
            count = mask.sum()
        else:
            median_days = None
            count = 0
        results.append({
            "from_stage": from_stage,
            "to_stage": to_stage,
            "median_days": median_days,
            "deals_measured": count,
        })
    return pd.DataFrame(results)


def pipeline_summary(deals_df: pd.DataFrame) -> pd.DataFrame:
    """Summary stats grouped by pipeline."""
    return deals_df.groupby("pipeline").agg(
        total_deals=("deal_id", "count"),
        total_amount=("amount", "sum"),
        avg_amount=("amount", "mean"),
        teams=("team", "nunique"),
    ).reset_index()


# ─── MAIN ───────────────────────────────────────────────────────────────────────


def main():
    folder = os.path.dirname(os.path.abspath(__file__))

    # Load and validate
    raw_deals = load_json_files(folder)
    deals = deduplicate(raw_deals)

    # Build DataFrames
    deals_df = deals_to_dataframe(deals)
    ts_df = stage_timestamps_dataframe(deals)

    # Filter: Classic pipeline, New Business, Closed Won or Closed Lost
    mask = (
        (deals_df["pipeline"] == "Classic")
        & (deals_df["deal_type"] == "New Business")
        & (deals_df["stage"].isin(["Closed Won", "Closed Lost"]))
    )
    deals_df = deals_df[mask].reset_index(drop=True)
    ts_df = ts_df[ts_df["deal_id"].isin(deals_df["deal_id"])].reset_index(drop=True)

    print(f"\nFiltered to {len(deals_df)} deals (Classic / New Business / Closed Won or Lost)")

    # Print summary
    print("\n── Pipeline Summary ──")
    print(pipeline_summary(deals_df).to_string(index=False))

    print("\n── Classic Pipeline Conversion Rates ──")
    print(stage_conversion_rates(ts_df, "Classic").to_string(index=False))

    print("\n── Classic Time-in-Stage (median days) ──")
    print(time_in_stage(ts_df, "Classic").to_string(index=False))

    # Export
    deals_csv = os.path.join(folder, "deals.csv")
    ts_csv = os.path.join(folder, "stage_timestamps.csv")
    deals_df.to_csv(deals_csv, index=False)
    ts_df.to_csv(ts_csv, index=False)
    print(f"\nExported: {deals_csv}")
    print(f"Exported: {ts_csv}")


if __name__ == "__main__":
    main()
