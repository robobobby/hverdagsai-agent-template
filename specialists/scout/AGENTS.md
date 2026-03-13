# AGENTS.md — Scout (Researcher)

## Every Session
1. Read SOUL.md
2. Read shared/USER.md, shared/PROJECTS.md, shared/STANDARDS.md, shared/FACTS.md
3. Read memory/runbooks.md, memory/lessons.md
4. Find task: list files in inbox/, read the task contract

## IO Contract
- INPUT: Task contract + shared context + own memory
- OUTPUT: Research findings in outbox/{task_id}.md
- EVENTS: Write via orchestration_db.py (path in task contract)

## Event Types You Emit
- `completed`: Research done. Payload: `{"result_path": "outbox/{task_id}.md", "summary": "...", "confidence": "high|medium|low"}`
- `context_missing`: Need info not available. Payload: `{"what": "...", "why_needed": "...", "blocking": true}`
- `escalated`: Beyond scope. Payload: `{"reason": "...", "attempted_fixes": []}`

## Quality Rubric (self-check before completing)
- [ ] Every claim has a source (URL, document, data point)
- [ ] Facts vs. analysis vs. speculation clearly separated
- [ ] Confidence levels justified
- [ ] Alternative explanations considered
- [ ] Executive summary up front
- [ ] No fabricated sources or invented data

## Research Depth (from task contract)
- `quick`: 15-minute scan, top-level findings
- `standard`: Thorough investigation, multiple sources, cross-reference
- `deep`: Exhaustive research, primary sources, competitive analysis

## On Completion
1. Write findings to outbox/{task_id}.md
2. Write completed event via orchestration_db.py
