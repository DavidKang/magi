"""GitHub adapter: PR searches and details through gh's GraphQL API, built into entities."""

import json

from . import process
from ..domain.entities import FoundPr, PullRequest

HEAD_CI = "head: commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }"
CHECKS_PAGE = """pageInfo { hasNextPage endCursor }
  nodes { ... on CheckRun { name conclusion detailsUrl } ... on StatusContext { context state targetUrl } }"""
HEAD_CHECKS = f"head: commits(last: 1) {{ nodes {{ commit {{ statusCheckRollup {{ state contexts(first: 100) {{ {CHECKS_PAGE} }} }} }} }} }}"
LIGHT_FIELDS = f"url number updatedAt title headRefName mergeable author {{ login }} repository {{ nameWithOwner }} {HEAD_CI}"
CHECK_FIELDS = f"url number repository {{ nameWithOwner }} {HEAD_CHECKS}"
PR_FIELDS = f"""number title url updatedAt headRefName headRefOid isDraft createdAt reviewDecision mergeable author {{ login }}
  reviewRequests(first: 20) {{ nodes {{ requestedReviewer {{ __typename }} }} }}
  reviews(first: 100) {{ nodes {{ author {{ login }} body state submittedAt }} }}
  commits(last: 100) {{ nodes {{ commit {{ committedDate }} }} }}
  {HEAD_CI}
  reviewThreads(first: 100) {{ nodes {{ isResolved isOutdated path line
    comments(first: 50) {{ nodes {{ author {{ login }} body createdAt diffHunk url }} }} }} }}
  comments(first: 100) {{ nodes {{ author {{ __typename login }} body createdAt url }} }}"""
# Small batches in parallel: GitHub resolves the aliases of one query roughly in sequence.
PRS_PER_QUERY = 3
GHOST = {"login": "ghost"}
CI_STATES = {"SUCCESS": "passing", "FAILURE": "failing", "ERROR": "failing", "PENDING": "running", "EXPECTED": "running"}
# How a check run or a commit status ends when it fails.
FAILED_CHECKS = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "STARTUP_FAILURE", "ACTION_REQUIRED"}
LAST_PAGE = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}


def graphql(query):
    return process.run_json(["gh", "api", "graphql", "-f", f"query=query {{ {query} }}"])["data"]


def repository(owner_repo, number, fields):
    owner, name = owner_repo.split("/")
    return f'repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ pullRequest(number: {int(number)}) {{ {fields} }} }}'


def search_terms(keys):
    chunks = [keys[start:start + 6] for start in range(0, len(keys), 6)]
    return [[token for key in chunk for token in ("OR", key)][1:] for chunk in chunks]


def fetch_pr_states(urls):
    if not urls:
        return {}
    places = [url.split("/") for url in urls]
    data = graphql(" ".join(f"pr{i}: " + repository(f"{place[3]}/{place[4]}", place[6], "state") for i, place in enumerate(places)))
    return {url: data[f"pr{i}"]["pullRequest"]["state"] for i, url in enumerate(urls)}


def fetch_prs(candidates):
    return in_batches(fetch_pr_batch, candidates)


def fetch_failed_checks(candidates):
    """Each PR's failed checks, in the order asked."""
    return in_batches(fetch_checks_batch, candidates)


def in_batches(fetch_batch, candidates):
    candidates = list(candidates)
    batches = [candidates[start:start + PRS_PER_QUERY] for start in range(0, len(candidates), PRS_PER_QUERY)]
    return [found for batch in process.parallel(fetch_batch, batches) for found in batch]


def fetch_pr_batch(batch):
    data = graphql(" ".join(f"pr{i}: " + repository(repo, number, PR_FIELDS) for i, (repo, number) in enumerate(batch)))
    return [pr_from_graph(data[f"pr{i}"]["pullRequest"], repo) for i, (repo, _) in enumerate(batch)]


def fetch_checks_batch(batch):
    data = graphql(" ".join(f"pr{i}: " + repository(repo, number, CHECK_FIELDS) for i, (repo, number) in enumerate(batch)))
    return [failed_checks(data[f"pr{i}"]["pullRequest"]) for i in range(len(batch))]


def search_prs(query):
    data = graphql(f"search(type: ISSUE, query: {json.dumps(query)}, first: 100) {{ nodes {{ ... on PullRequest {{ {LIGHT_FIELDS} }} }} }}")
    return [light_pr(node) for node in data["search"]["nodes"]]


def light_pr(node):
    owner_repo = node["repository"]["nameWithOwner"]
    return FoundPr(url=node["url"], number=node["number"], updated_at=node["updatedAt"], title=node["title"],
                   head_ref_name=node["headRefName"], mergeable=node["mergeable"], author=node["author"] or GHOST,
                   name_with_owner=owner_repo, repo=owner_repo.split("/")[1], ci=head_ci(node))


def head_rollup(node):
    head = node["head"]["nodes"]
    return head[0]["commit"]["statusCheckRollup"] if head else None


def head_ci(node):
    rollup = head_rollup(node)
    return CI_STATES[rollup["state"]] if rollup else "none"


def failed_checks(node):
    """The head commit's failed checks, each linked to its log, or to the PR's checks when GitHub gives none."""
    rollup = head_rollup(node)
    found = [check(context) for context in head_checks(node, rollup)] if rollup else []
    return [{"name": name, "url": url if plain_https(url) else node["url"] + "/checks"} for name, ended, url in found if ended in FAILED_CHECKS]


def head_checks(node, rollup):
    """The head commit's checks: a failed rollup with over 100 asks for the rest, so no failed check goes unnamed."""
    page = rollup["contexts"]
    found = page["nodes"]
    while CI_STATES[rollup["state"]] == "failing" and page["pageInfo"]["hasNextPage"]:
        page = next_checks(node, page["pageInfo"]["endCursor"])
        found = found + page["nodes"]
    return found


def next_checks(node, after):
    fields = f"commits(last: 1) {{ nodes {{ commit {{ statusCheckRollup {{ contexts(first: 100, after: {json.dumps(after)}) {{ {CHECKS_PAGE} }} }} }} }} }}"
    pr = graphql(repository(node["repository"]["nameWithOwner"], node["number"], fields))["repository"]["pullRequest"]
    rollup = pr["commits"]["nodes"][0]["commit"]["statusCheckRollup"]
    # A push since the first page leaves a new head, with no checks yet: the pages end there.
    return rollup["contexts"] if rollup else LAST_PAGE


def plain_https(url):
    """Whoever posts a check sets its url: only an https one without quotes is safe to open and to put in a link."""
    return bool(url) and url.startswith("https://") and not any(quote in url for quote in "'\"")


def check(context):
    """A check run or a commit status, as its name, how it ended and where its log is."""
    if "context" in context:
        return context["context"], context["state"], context["targetUrl"]
    return context["name"], context["conclusion"], context["detailsUrl"]


def pr_from_graph(pr, repo):
    # The failed checks come in their own query, asked only for the PRs whose CI failed.
    return PullRequest(
        number=pr["number"], title=pr["title"], url=pr["url"], updated_at=pr["updatedAt"], head_ref_name=pr["headRefName"],
        head_ref_oid=pr["headRefOid"], is_draft=pr["isDraft"], created_at=pr["createdAt"], review_decision=pr["reviewDecision"],
        mergeable=pr["mergeable"], author=pr["author"] or GHOST, review_requests=pr["reviewRequests"]["nodes"],
        reviews=with_authors(pr["reviews"]["nodes"]), commits=[node["commit"] for node in pr["commits"]["nodes"]],
        threads=[{**thread, "comments": with_authors(thread["comments"]["nodes"])} for thread in pr["reviewThreads"]["nodes"]
                 if not thread["isResolved"]],
        conversation=[comment for comment in pr["comments"]["nodes"] if comment["author"] and not is_bot(comment["author"])],
        repo=repo.split("/")[1], ci=head_ci(pr), failed_checks=[])


def with_authors(nodes):
    # GraphQL gives a deleted account a null author.
    return [{**node, "author": node["author"] or GHOST} for node in nodes]


def is_bot(author):
    return author["__typename"] == "Bot" or author["login"].lower().endswith("bot")
