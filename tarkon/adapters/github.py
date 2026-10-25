"""GitHub adapter: PR searches and details through gh's GraphQL API, built into entities."""

import json

from . import process
from ..domain.entities import FoundPr, PullRequest

HEAD_CI = "head: commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }"
LIGHT_FIELDS = f"url number updatedAt title headRefName mergeable author {{ login }} repository {{ nameWithOwner }} {HEAD_CI}"
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
    candidates = list(candidates)
    batches = [candidates[start:start + PRS_PER_QUERY] for start in range(0, len(candidates), PRS_PER_QUERY)]
    return [pr for batch in process.parallel(fetch_pr_batch, batches) for pr in batch]


def fetch_pr_batch(batch):
    data = graphql(" ".join(f"pr{i}: " + repository(repo, number, PR_FIELDS) for i, (repo, number) in enumerate(batch)))
    return [pr_from_graph(data[f"pr{i}"]["pullRequest"], repo) for i, (repo, _) in enumerate(batch)]


def search_prs(query):
    data = graphql(f"search(type: ISSUE, query: {json.dumps(query)}, first: 100) {{ nodes {{ ... on PullRequest {{ {LIGHT_FIELDS} }} }} }}")
    return [light_pr(node) for node in data["search"]["nodes"]]


def light_pr(node):
    owner_repo = node["repository"]["nameWithOwner"]
    return FoundPr(url=node["url"], number=node["number"], updated_at=node["updatedAt"], title=node["title"],
                   head_ref_name=node["headRefName"], mergeable=node["mergeable"], author=node["author"] or GHOST,
                   name_with_owner=owner_repo, repo=owner_repo.split("/")[1], ci=head_ci(node))


def head_ci(node):
    head = node["head"]["nodes"]
    rollup = head[0]["commit"]["statusCheckRollup"] if head else None
    return CI_STATES[rollup["state"]] if rollup else "none"


def pr_from_graph(pr, repo):
    return PullRequest(
        number=pr["number"], title=pr["title"], url=pr["url"], updated_at=pr["updatedAt"], head_ref_name=pr["headRefName"],
        head_ref_oid=pr["headRefOid"], is_draft=pr["isDraft"], created_at=pr["createdAt"], review_decision=pr["reviewDecision"],
        mergeable=pr["mergeable"], author=pr["author"] or GHOST, review_requests=pr["reviewRequests"]["nodes"],
        reviews=with_authors(pr["reviews"]["nodes"]), commits=[node["commit"] for node in pr["commits"]["nodes"]],
        threads=[{**thread, "comments": with_authors(thread["comments"]["nodes"])} for thread in pr["reviewThreads"]["nodes"]
                 if not thread["isResolved"]],
        conversation=[comment for comment in pr["comments"]["nodes"] if comment["author"] and not is_bot(comment["author"])],
        repo=repo.split("/")[1], ci=head_ci(pr))


def with_authors(nodes):
    # GraphQL gives a deleted account a null author.
    return [{**node, "author": node["author"] or GHOST} for node in nodes]


def is_bot(author):
    return author["__typename"] == "Bot" or author["login"].lower().endswith("bot")
