Issue tracker: GitHub

Issues PRDs repo live GitHub issues. Use`gh`CLI all operations.

Conventions

**Create issue**:`gh issue create --title "..." --body "..."`. Use heredoc multi-line bodies.
**Read issue**:`gh issue view <number> --comments`filtering comments`jq`fetching labels.
**List issues**:`gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`appropriate`--label``--state`filters.
**Comment issue**:`gh issue comment <number> --body "..."`
**Apply / remove labels**:`gh issue edit <number> --add-label "..."`/`--remove-label "..."`
**Close**:`gh issue close <number> --comment "..."`

Infer repo`git remote -v`—`gh`automatically when run inside clone.

Pull requests triage surface

**PRs request surface: no.** _(Set`yes`repo treats external PRs feature requests;`/triage`reads flag.)_

When set`yes`PRs run through same labels states issues, using`gh pr`equivalents:

**Read PR**:`gh pr view <number> --comments``gh pr diff <number>`diff.
**List external PRs triage**:`gh pr list --state open --json number,title,body,labels,author,authorAssociation,comments`then keep only`authorAssociation``CONTRIBUTOR``FIRST_TIME_CONTRIBUTOR`,`NONE`(drop`OWNER`/`MEMBER`/`COLLABORATOR`).
**Comment / label / close**:`gh pr comment``gh pr edit --add-label`/`--remove-label``gh pr close`.

GitHub shares one number space across issues PRs, bare`#42`either — resolve`gh pr view 42`fall back`gh issue view 42`.

When skill says "publish issue tracker"

Create GitHub issue.

When skill says "fetch relevant ticket"

Run`gh issue view <number> --comments`.

Wayfinding operations

`/wayfinder`. **map** single issue **child** issues tickets.

**Map**: single issue labelled`wayfinder:map`holding Notes / Decisions-so-far / Fog body.`gh issue create --label wayfinder:map`.
**Child ticket**: issue linked map GitHub sub-issue`gh api`sub-issues endpoint). Where sub-issues aren't enabled, add child task list map body put`Part of #<map>`top child body. Labels:`wayfinder:<type>`(`research`/`prototype`/`grilling`/`task`). Once claimed, ticket assigned driving dev.
**Blocking**: GitHub's **native issue dependencies** canonical, UI-visible representation. Add edge`gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`where`<blocker-db-id>`blocker's numeric **database id**`gh api repos/<owner>/<repo>/issues/<n> --jq .id`_not_`#number``node_id`). GitHub reports`issue_dependencies_summary.blocked_by`(open blockers only live gate). Where dependencies aren't available, fall back`Blocked by: #<n>, #<n>`line top child body. ticket unblocked when every blocker closed.
**Frontier query**: list map's open children`gh issue list --state open`scoped map's sub-issues / task list), drop any open blocker`issue_dependencies_summary.blocked_by > 0`, open issue`Blocked by`line) assignee; first map order wins.
**Claim**:`gh issue edit <n> --add-assignee @me`session's first write.
**Resolve**:`gh issue comment <n> --body "<answer>"`then`gh issue close <n>`then append contextpointer (gist + link)map's Decisions-so-far.
