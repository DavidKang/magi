"""The Jira keys a PR names, in its title or its branch."""

import re


def ticket_keys_in(pr, project):
    return {k.upper() for k in re.findall(rf"{re.escape(project)}-\d+", f"{pr.title} {pr.head_ref_name}", flags=re.I)}


def title_keys_in(pr, project):
    return set(re.findall(r"\[([A-Z][A-Z0-9]+-\d+)\]", pr.title)) | ticket_keys_in(pr, project)


def title_parts(title):
    # A leading [KEY] is the linked part of a PR title; the rest follows it after one space.
    linked, rest = re.fullmatch(r"(\[[^\]]+\])?\s*(.*)", title).groups()
    return (linked, rest) if linked else (title, "")
