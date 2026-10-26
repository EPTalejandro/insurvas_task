"""Ranking knobs. Every number that changes the ranking lives here, so a change is one line."""

# No 1-day window: a post that young has not had time to show its engagement.
WINDOWS = (7, 30, 90)  # days
DEFAULT_WINDOW = 7

# How much each metric counts toward a post's engagement.
ENGAGEMENT_WEIGHTS = {"likes": 1.0, "comments": 1.0, "shares": 1.0}

# How the score mixes three percentiles (within platform and window):
#   impact          = engagement a post earned, in absolute numbers
#   outperformance  = impact compared with the creator's usual
#   reach           = views
# Ratios to followers are not in the score: tiny channels win any ratio, and we want
# content that really got engagement.
BLEND = {"impact": 0.60, "outperformance": 0.25, "reach": 0.15}

# A small nudge for short videos: they earn fewer likes and comments per view than long ones,
# so on engagement alone they sink. The final score is multiplied, then capped at 100.
FORMAT_BOOST = {"short_video": 1.10, "reel": 1.10}

MIN_ENGAGEMENT_TO_RANK = 5  # likes + comments + shares; below this a post is noise
BASELINE_FLOOR = 5.0  # a creator's "usual" never counts as less than this (adjusted engagement)

MIN_POST_AGE_HOURS = 6  # younger posts have not collected their engagement yet
MIN_BASELINE_POSTS = 3  # posts needed to know a creator's "usual" engagement
MIN_GROUP_SIZE = 5  # insights hide groups smaller than this

# Posts a competitor needs in a window before its score is trusted.
MIN_POSTS_BY_WINDOW = {7: 3, 30: 5, 90: 5}

STRONG_SCORE, GOOD_SCORE = 90, 70  # badge thresholds in the UI

# Hashtag posts have no known author, so we only rank the ones whose caption looks US-based.
HASHTAG_LOCATIONS = ("likely_us", "probable_us")

BASELINE_DAYS = 90  # a creator's usual engagement is measured over this period
CONSISTENT_SCORE = 50  # a post at or above this counts as "good" for consistency
OUTPERFORM_REASON_MIN = 1.5  # show "N× usual engagement" only above this
