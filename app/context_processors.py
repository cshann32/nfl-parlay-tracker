"""
Jinja2 context processors.
Injects shared lookup tables into every template automatically.
"""

# Human-readable labels for stat categories
CAT_LABELS = {
    "general":               "General",
    "passing":               "Passing",
    "rushing":               "Rushing",
    "receiving":             "Receiving",
    "defensive":             "Defensive",
    "kicking":               "Kicking",
    "punting":               "Punting",
    "scoring":               "Scoring",
    "fumbles":               "Fumbles",
    "interceptions":         "Interceptions",
    "kickreturns":           "Kick Returns",
    "puntreturns":           "Punt Returns",
    "defensiveinterceptions":"Def. Interceptions",
    "returning":             "Returns",
    "ngs_passing":           "NGS — Passing",
    "ngs_rushing":           "NGS — Rushing",
    "ngs_receiving":         "NGS — Receiving",
    "adv_passing":           "Advanced Passing",
    "adv_rushing":           "Advanced Rushing",
    "adv_receiving":         "Advanced Receiving",
}

# Human-readable labels for individual stat types (ESPN abbreviations + custom)
STAT_LABELS = {
    # General
    "GP": "Games",        "GS": "Starts",

    # Passing
    "CMP": "Comp",        "ATT": "Att",         "YDS": "Yards",
    "TD": "TDs",          "INT": "INTs",        "RTG": "Rating",
    "RAT": "Rating",      "CMP%": "Comp %",     "YDS/G": "Yds/Gm",
    "INT%": "INT %",      "TD%": "TD %",        "AG": "Avg Gain",
    "QBR": "QBR",         "EQBR": "ESPN QBR",   "TP": "TDs/Gm",
    "TP/G": "TD/Gm",      "TGP": "Total Gms",
    "NTYDS": "Net Yds",   "NTYDS/G": "Net Yds/Gm", "NATT": "Net Att",
    "NYDS": "Net Pass Yds","NYDS/G": "Net Yds/Gm", "NYDS/PA": "Net Yds/Att",
    "SACK": "Sacks",      "SYL": "Sack Yds Lost",
    "PYAC": "Pass YAC",   "PY@C": "Yds @ Catch",
    "BIGP": "Big Plays",  "FIRST": "1st Downs",

    # Rushing
    "CAR": "Carries",     "AVG": "Avg",         "LNG": "Long",
    "FD": "1st Downs",    "BIG": "20+ Yds",     "SCRIM": "Scrimmage",
    "SCRIM/G": "Scrim/Gm","TYDS": "Total Yds",

    # Receiving
    "REC": "Rec",         "TGTS": "Targets",    "YAC": "YAC",
    "Y@C": "Yds @ Catch", "TOP": "Time of Poss",

    # Fumbles
    "FUM": "Fumbles",     "LST": "Fum Lost",    "FL": "Fum Lost",

    # Defensive
    "TOT": "Tackles",     "SOLO": "Solo Tkl",   "ASST": "Ast Tkl",
    "AST": "Ast Tkl",     "TFL": "TFL",         "SCK": "Sacks",
    "SCKYDS": "Sack Yds", "YDS/SACK": "Yds/Sack",
    "FF": "Forced Fum",   "FR": "Fum Rec",      "PD": "Pass Def",
    "SAFE": "Safety",

    # Kicking
    "FGM": "FG Made",     "FGA": "FG Att",      "FG%": "FG %",
    "FG": "FG",           "PCT": "FG %",        "LK": "Long FG",
    "XPM": "XP Made",     "XPA": "XP Att",      "XPB": "XP Blk",

    # Punting
    "NO": "Punts",        "PUNTS": "Punts",     "NET": "Net Avg",
    "IN20": "Inside 20",  "IN20%": "In20 %",    "TB": "Touchbacks",
    "TB%": "TB %",

    # Returns
    "KR": "KR Att",       "YDS/R": "Yds/Ret",  "YDS/KR": "Yds/KR",
    "FC": "Fair Catch",

    # Scoring
    "PTS": "Points",      "DFTD": "Def TD",     "BPTD": "Blk Ret TD",
    "MISCTD": "Misc TD",  "OFTD": "Off TD",
    "2PT": "2-Pt Conv",   "2PTP": "2-Pt Poss",  "2PTPA": "2-Pt Att",

    # ESPN ratings
    "ESPNWR": "ESPN Rtg", "ESPNRB": "ESPN Rtg", "OP": "Opp",

    # NGS Passing
    "ATT2TH":  "Time to Throw",
    "AVG_IAY": "Avg Air Yds",
    "AVG_CAY": "Comp Air Yds",
    "AGG":     "Aggressiveness",
    "CPOE":    "CPOE",
    "AVG_AYTS":"Air Yds to Sticks",
    "AVG_AYD": "Air Yds Diff",

    # NGS Rushing
    "EFF":     "Rush Eff",
    "PCT8DEF": "vs 8 in Box",
    "TT_LOS":  "Time to LOS",
    "RYOE_PA": "Rush Yds OE/Att",
    "RPOE":    "Rush % OE",
    "EXP_RY":  "Exp Rush Yds",

    # NGS Receiving
    "CUSHION": "Cushion",
    "SEP":     "Separation",
    "IAY_SH":  "Air Yds Share",
    "AVG_YAC": "Avg YAC",
    "YAC_AE":  "YAC Above Exp",

    # Advanced passing
    "PASS_EPA": "Pass EPA",
    "PASS_AY":  "Pass Air Yds",
    "PASS_YAC": "Pass YAC",
    "PACR":     "PACR",
    "DAKOTA":   "DAKOTA",

    # Advanced rushing
    "RUSH_EPA": "Rush EPA",

    # Advanced receiving
    "REC_EPA":  "Rec EPA",
    "REC_AY":   "Rec Air Yds",
    "REC_YAC":  "Rec YAC",
    "RACR":     "RACR",
    "TGT_SH":   "Target Share",
    "AY_SH":    "Air Yds Share",
    "WOPR":     "WOPR",
    "FPTS":     "Fantasy Pts",
    "FPTS_PPR": "Fantasy (PPR)",
}

# Key stats shown in the spotlight row per position
# Format: [category, stat_type, display_label]
SPOTLIGHT = {
    "QB":  [["general","GP","Games"],["passing","CMP","Comp"],["passing","YDS","Pass Yds"],
            ["passing","TD","TDs"],["passing","INT","INTs"],["passing","RTG","Rating"]],
    "WR":  [["general","GP","Games"],["receiving","REC","Rec"],["receiving","YDS","Yards"],
            ["receiving","TD","TDs"],["receiving","TGTS","Targets"],["receiving","LNG","Long"]],
    "TE":  [["general","GP","Games"],["receiving","REC","Rec"],["receiving","YDS","Yards"],
            ["receiving","TD","TDs"],["receiving","TGTS","Targets"],["receiving","FD","1st Downs"]],
    "RB":  [["general","GP","Games"],["rushing","CAR","Carries"],["rushing","YDS","Rush Yds"],
            ["rushing","TD","TDs"],["receiving","REC","Rec"],["receiving","YDS","Rec Yds"]],
    "FB":  [["general","GP","Games"],["rushing","CAR","Carries"],["rushing","YDS","Rush Yds"],
            ["rushing","TD","TDs"],["receiving","REC","Rec"],["receiving","YDS","Rec Yds"]],
    "K":   [["general","GP","Games"],["kicking","FGM","FG Made"],["kicking","FGA","FG Att"],
            ["kicking","PCT","FG %"],["kicking","XPM","XP Made"],["kicking","LNG","Long FG"]],
    "PK":  [["general","GP","Games"],["kicking","FGM","FG Made"],["kicking","FGA","FG Att"],
            ["kicking","PCT","FG %"],["kicking","XPM","XP Made"],["kicking","LNG","Long FG"]],
    "P":   [["general","GP","Games"],["punting","NO","Punts"],["punting","YDS","Tot Yds"],
            ["punting","AVG","Avg"],["punting","NET","Net Avg"],["punting","LNG","Long"]],
    "LB":  [["general","GP","Games"],["defensive","TOT","Tackles"],["defensive","SOLO","Solo"],
            ["defensive","SCK","Sacks"],["defensive","TFL","TFL"],["defensive","FF","Forced Fum"]],
    "OLB": [["general","GP","Games"],["defensive","TOT","Tackles"],["defensive","SOLO","Solo"],
            ["defensive","SCK","Sacks"],["defensive","TFL","TFL"],["defensive","FF","Forced Fum"]],
    "MLB": [["general","GP","Games"],["defensive","TOT","Tackles"],["defensive","SOLO","Solo"],
            ["defensive","SCK","Sacks"],["defensive","TFL","TFL"],["defensive","FF","Forced Fum"]],
    "ILB": [["general","GP","Games"],["defensive","TOT","Tackles"],["defensive","SOLO","Solo"],
            ["defensive","SCK","Sacks"],["defensive","TFL","TFL"],["defensive","FF","Forced Fum"]],
    "DE":  [["general","GP","Games"],["defensive","SCK","Sacks"],["defensive","TOT","Tackles"],
            ["defensive","TFL","TFL"],["defensive","FF","Forced Fum"],["defensive","SOLO","Solo"]],
    "DT":  [["general","GP","Games"],["defensive","SCK","Sacks"],["defensive","TOT","Tackles"],
            ["defensive","TFL","TFL"],["defensive","FF","Forced Fum"],["defensive","SOLO","Solo"]],
    "NT":  [["general","GP","Games"],["defensive","SCK","Sacks"],["defensive","TOT","Tackles"],
            ["defensive","TFL","TFL"],["defensive","FF","Forced Fum"],["defensive","SOLO","Solo"]],
    "CB":  [["general","GP","Games"],["defensive","INT","INTs"],["defensive","PD","Pass Def"],
            ["defensive","TOT","Tackles"],["defensive","SOLO","Solo"],["defensive","FF","Forced Fum"]],
    "S":   [["general","GP","Games"],["defensive","INT","INTs"],["defensive","PD","Pass Def"],
            ["defensive","TOT","Tackles"],["defensive","SOLO","Solo"],["defensive","FF","Forced Fum"]],
    "SS":  [["general","GP","Games"],["defensive","INT","INTs"],["defensive","PD","Pass Def"],
            ["defensive","TOT","Tackles"],["defensive","SOLO","Solo"],["defensive","FF","Forced Fum"]],
    "FS":  [["general","GP","Games"],["defensive","INT","INTs"],["defensive","PD","Pass Def"],
            ["defensive","TOT","Tackles"],["defensive","SOLO","Solo"],["defensive","FF","Forced Fum"]],
    "DB":  [["general","GP","Games"],["defensive","INT","INTs"],["defensive","PD","Pass Def"],
            ["defensive","TOT","Tackles"],["defensive","SOLO","Solo"],["defensive","FF","Forced Fum"]],
}

# Default spotlight for unknown/unlisted positions
SPOTLIGHT_DEFAULT = [
    ["general","GP","Games"],    ["rushing","YDS","Rush Yds"],
    ["receiving","YDS","Rec Yds"],["rushing","TD","TDs"],
    ["receiving","REC","Rec"],   ["receiving","TGTS","Targets"],
]


def inject_stat_labels():
    """Inject stat label dicts into all template contexts."""
    return {
        "CAT_LABELS":       CAT_LABELS,
        "STAT_LABELS":      STAT_LABELS,
        "SPOTLIGHT":        SPOTLIGHT,
        "SPOTLIGHT_DEFAULT": SPOTLIGHT_DEFAULT,
    }
