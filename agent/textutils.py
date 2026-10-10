"""Shared text helpers: tokenizing, topic signatures, keyword lists."""
from __future__ import annotations

import re
from typing import Set, Tuple

STOPWORDS = set("""
a an the and or but if then so to of in on at by for from with without into onto over under
is are was were be been being am do does did done has have had having will would shall should
can could may might must it its this that these those there here i me my we our us you your yours
he she they them their his her him what which who whom whose when where why how all any both each
few more most other some such no nor not only own same than too very just also about as up down out
off again further once ok okay pls please plz guys everyone all hi hello hey dear folks team's
s t d ll re ve m o y let lets know anyone anybody someone somebody one get got go going need needs
make sure kindly note noted asap regards thanks thank yes yeah yep nope same new via per use
been being happening happen anything everything something
""".split())

MONTH_WORDS = set("""
jan january feb february mar march apr april may jun june jul july aug august sep sept september
oct october nov november dec december
""".split())
DAY_WORDS = set("""
monday tuesday wednesday thursday friday saturday sunday today tomorrow tonight tmrw tmr day week
weekend morning evening afternoon night noon midnight eod am pm hrs hr pm. am. th st nd rd
""".split())
CHANGE_WORDS = set("""
update updated updates moved move shifted shift postponed postpone preponed prepone rescheduled reschedule
changed change extended extend revised revise cancelled canceled cancel now instead new venue
deadline due last date closes close closing scheduled schedule held per usual
""".split())
HEDGE_PHRASES = [
    "i heard", "heard that", "someone said", "somebody said", "people are saying", "apparently",
    "rumour", "rumor", "not sure", "maybe", "might be", "probably", "i think", "chances are",
    "unconfirmed", "is it true", "not confirmed", "whatsapp university",
    "kya sach", "suna hai", "sources say", "possibly", "can anyone confirm",
]
GENERIC = set("""
students student year batch class sem semester group link form portal details info information
message msg reminder important attention notice official guys bro everyone people all college campus
heard said sure think rumours rumours rumor rumors ignore fake true false
""".split())

FIRST_WORD_WEAK = set("""
submit upload use bring register apply fill complete prepare attend join check send internal final
reach carry pay finish start read revise study share collect meet don't dont do here there today
""".split())

# Nouns that name "the thing" an announcement is about.
HEAD_NOUNS = set("""
assignment assignments quiz exam exams midsem endsem test viva lab practical project report
internship internships placement drive interview hackathon sih ppt presentation submission
registration workshop seminar webinar fest briefing meeting event events competition contest
round deadline fee fees scholarship lecture class talk orientation induction tutorial
""".split())


def normalize_text(text: str) -> str:
    t = text.lower()
    t = re.sub(r"https?://\S+|www\.\S+", " ", t)
    t = re.sub(r"\bmid[\s\-]?sems?\b", "midsem", t)
    t = re.sub(r"\bend[\s\-]?sems?\b", "endsem", t)
    t = re.sub(r"\bpre[\s\-]?placement\b", "preplacement", t)
    return t


def tokenize(text: str) -> list:
    return re.findall(r"[a-z0-9]+", normalize_text(text))


def stem(token: str) -> str:
    for suf in ("ings", "ing", "ies", "ed", "es", "s"):
        if len(token) > len(suf) + 2 and token.endswith(suf):
            if suf == "ies":
                return token[:-3] + "y"
            return token[: -len(suf)]
    return token


def topic_signature(text: str) -> Tuple[Set[str], Set[str]]:
    """Return (topic_tokens, strong_tokens).

    Topic tokens describe *what* a message is about (dates, times, venues,
    hedges and change verbs removed). Strong tokens are entity-like: acronyms,
    proper nouns, and head nouns such as 'assignment' or 'internship'.
    """
    tokens = []
    for tok in tokenize(text):
        if tok in STOPWORDS or tok in MONTH_WORDS or tok in DAY_WORDS or tok in CHANGE_WORDS:
            continue
        if tok in GENERIC or tok.isdigit() or re.fullmatch(r"\d+(st|nd|rd|th|am|pm)", tok):
            continue
        if tok in {"room", "hall", "auditorium", "lab", "lt", "block", "main", "seminar"}:
            continue
        if len(tok) < 2:
            continue
        tokens.append(tok)
    topic = set(tokens)

    strong: Set[str] = set()
    raw_text = re.sub(r"https?://\S+", " ", text)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9&]*", raw_text):
        low = word.lower()
        if low not in topic:
            continue
        if word.isupper() and len(word) >= 2:          # SIH, OS, DBMS, TCS
            strong.add(low)
        elif word[0].isupper() and low not in STOPWORDS:  # Infosys, Amazon
            strong.add(low)
    strong |= {t for t in topic if t in HEAD_NOUNS}
    # A capitalised first word is only weak if it's an ordinary verb/adjective.
    first = re.findall(r"[A-Za-z]+", raw_text)[:1]
    if first and first[0].lower() in FIRST_WORD_WEAK and not first[0].isupper():
        strong.discard(first[0].lower())
    return topic, strong


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def has_hedge(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in HEDGE_PHRASES)


def hedge_hits(text: str) -> list:
    low = text.lower()
    return [p for p in HEDGE_PHRASES if p in low]
