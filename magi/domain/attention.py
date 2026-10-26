"""What on the board needs someone's attention: tickets and PRs whose state disagrees, or that have waited too long."""

from .ages import days_since
from .changes import pr_subject, ticket_subject
from .review import looks_ready_but_blocked, review_state
from .status import status_label

ACTIVE_COLUMNS = {"doing", "review", "deploy"}
STALE_PR_DAYS = 3


def attention_items(all_tickets, prs, merged_by_ticket, settings):
    items = []

    def flag(subject, reason):
        items.append({"subject": subject, "reason": reason})
    for t in all_tickets:
        open_for_review = [pr for pr in t.prs if not pr.is_draft]
        if t.column == "doing":
            for pr in open_for_review:
                flag(pr_subject(pr.url, f"{pr.repo}#{pr.number}", pr.title), "Open for review, but the ticket is still In progress. Move it to In review?")
        if t.column in {"doing", "review"} and not t.prs:
            for merged in merged_by_ticket.get(t.key, []):
                flag(merged, f"Merged, but the ticket is still {status_label(t.status)} with no other open PR. Move it?")
        if t.column == "review" and not t.prs and not merged_by_ticket.get(t.key):
            flag(ticket_subject(t.key, settings.jira_browse, t.summary), "In review with no open PR.")
        if t.column == "done":
            for pr in t.prs:
                flag(pr_subject(pr.url, f"{pr.repo}#{pr.number}", pr.title), "Still open, but the ticket is already done.")
        if t.column in ACTIVE_COLUMNS and t.assignee == "Unassigned":
            flag(ticket_subject(t.key, settings.jira_browse, t.summary), "Active with no owner.")
    for pr in prs:
        subject = pr_subject(pr.url, f"{pr.repo}#{pr.number}", pr.title)
        if looks_ready_but_blocked(pr):
            reason = "red CI" if pr.ci == "failing" else "conflicts"
            flag(subject, f"Approved, but it has {reason}.")
        if review_state(pr)[0] == "waiting" and days_since(pr.created_at) > STALE_PR_DAYS:
            flag(subject, f"{days_since(pr.created_at)} days without any review.")
    return items
