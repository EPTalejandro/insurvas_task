"""The label vocabulary. Single source of truth: rules, Gemini and the API all read it.

Labels come from closed lists, otherwise "IUL", "indexed universal life" and "IUL explained"
would count as three topics and the insights would be meaningless.
Changing any list means bumping TAXONOMY_VERSION, so old labels are redone.
"""

TAXONOMY_VERSION = 2  # 2: added the flex flag

# A flex post is labeled like any other but never ranked: it gets engagement without giving the
# viewer anything to learn from or copy.
FLEX_DEFINITION = (
    "the post's main point is showing off results (income, commissions, production or sales "
    "records, awards, rankings, cars, lifestyle) with no lesson, tip or information a viewer "
    "could use. A post that shows a result and then explains how it was done is not a flex."
)

TOPICS: dict[str, str] = {
    "term_life": "Term life insurance",
    "whole_life": "Whole life and permanent insurance, cash value",
    "iul": "Indexed universal life (IUL)",
    "final_expense": "Final expense, burial and funeral insurance",
    "mortgage_protection": "Mortgage protection insurance",
    "annuities_retirement": "Annuities, retirement income, 401k and pensions",
    "estate_and_tax": "Estate planning, inheritance, tax-free wealth transfer",
    "living_benefits": "Living benefits, chronic or critical illness riders",
    "infinite_banking": "Infinite banking, being your own bank",
    "agent_recruiting": "Recruiting agents, joining a team or agency",
    "sales_training": "Sales training for agents: leads, scripts, closing",
    "client_story": "A real client or claim story",
    "myth_busting": "Myths, scams and common mistakes",
    "general_education": "General explanation of how insurance works",
    "other": "None of the above",
}

HOOKS: dict[str, str] = {
    "question": "Opens with a question",
    "statistic": "Opens with a number, amount or percentage",
    "personal_story": "Opens with the creator's own experience",
    "contrarian": "Challenges common belief: myths, lies, 'actually'",
    "warning": "Warns the viewer: avoid, never, mistakes",
    "how_to_list": "Promises steps or a list: 'how to', '5 ways'",
    "social_proof": "Reviews, testimonials, results from clients",
    "curiosity_gap": "Teases something the viewer must watch to learn",
    "direct_offer": "Offers a quote, call or free help right away",
    "none": "No clear hook",
}

CTAS: dict[str, str] = {
    "book_call": "Book or schedule a call, get a quote",
    "comment_or_dm_keyword": "Comment a word or send a DM",
    "link_in_bio": "Click the link in the bio or description",
    "follow_subscribe": "Follow or subscribe",
    "join_team": "Join the team or become an agent",
    "call_or_text": "Call or text a number",
    "none": "No call to action",
}

# What the format filter offers. Stored formats are finer (a Reel is a short video, a carousel is
# a set of images), but offering both would be redundant, so the filter uses these three groups.
# group -> (description, stored formats in it)
FORMAT_GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "long_video": ("Videos longer than 3 minutes", ("long_video", "video")),
    "short_video": ("Videos of 3 minutes or less, and Reels", ("short_video", "reel")),
    "image": ("Single images and image carousels", ("image", "carousel")),
}

# Formats come from the platform's data (not from a labeler), but the list lives here so the
# API can offer them as filters.
FORMATS: dict[str, str] = {
    "short_video": "YouTube video of 3 minutes or less",
    "long_video": "YouTube video longer than 3 minutes",
    "reel": "Instagram Reel",
    "video": "Other video",
    "image": "Single image",
    "carousel": "Several images or videos in one post",
    "text": "Text only",
    "link": "Link to something else",
}
