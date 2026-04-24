# Task Review Template

Use this template for review files inside `worklog/<username>/<worklog-id>/tasks/`.

## Metadata

- Task ID: `taskNN`
- Review Round: `1`
- Reviewer:
- Review Date:
- Status: `pending`

## Scope Reviewed

What was reviewed.

## Findings

- Finding 1

## Risks

- Risk 1

## Required Changes

- Change 1

## Final Decision

- `approved`
- `approved_with_comments`
- `changes_requested`

## Notes

Additional reviewer notes.

## Follow-Up

- If the decision is `changes_requested`, create the next review file as `taskNN_review{K+1}.md` after fixes are applied.
- If the decision is `approved` or `approved_with_comments`, the next action is to ask `DEV` to create the commit for this atomic task.
