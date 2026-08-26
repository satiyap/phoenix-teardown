# Exit Criteria

The teardown is complete only when every question below has a written answer
that cites evidence. `tools/check_exit_criteria.py` parses this file: it counts
a question answered when the `Answer` line is non-empty and does not contain
`TODO`.

Rule: if several of these still say "we'll figure it out later," the teardown
has not gone deep enough. That is the whole reason this file exists.

Answer format — replace the `TODO` and keep the `Answer:` prefix:

```
### Q1. What exactly is an Agent?
Answer: TODO
Evidence: ADR-0001; projects/letta, projects/cloudflare-agents
```

---

## Agent model

### Q1. What exactly is an Agent?
Answer: TODO
Evidence:

### Q2. Is an Agent persistent?
Answer: TODO
Evidence:

### Q3. What is a Run?
Answer: TODO
Evidence:

### Q4. What is a Task, and how does it differ from a Run?
Answer: TODO
Evidence:

### Q5. What is a Session, and what is it attached to?
Answer: TODO
Evidence:

## Runtime

### Q6. Who starts the agent?
Answer: TODO
Evidence:

### Q7. Where does it run?
Answer: TODO
Evidence:

### Q8. How does it recover from failure?
Answer: TODO
Evidence:

### Q9. How does it wake?
Answer: TODO
Evidence:

### Q10. How is it cancelled, and does cancellation propagate?
Answer: TODO
Evidence:

## Communication

### Q11. How do agents communicate?
Answer: TODO
Evidence:

### Q12. How do agents discover each other?
Answer: TODO
Evidence:

### Q13. How does one agent delegate to another?
Answer: TODO
Evidence:

## Context

### Q14. Who owns memory?
Answer: TODO
Evidence:

### Q15. Who owns conversation state?
Answer: TODO
Evidence:

### Q16. How is context shared between principals?
Answer: TODO
Evidence:

## Humans

### Q17. How does a human intervene in a running agent?
Answer: TODO
Evidence:

### Q18. How do humans and agents collaborate on shared work?
Answer: TODO
Evidence:

## Security

### Q19. What identity does an agent authenticate as?
Answer: TODO
Evidence:

### Q20. Whose credentials apply when an agent delegates?
Answer: TODO
Evidence:

### Q21. Where are policy decisions enforced?
Answer: TODO
Evidence:

## Platform boundary

### Q22. What do we build?
Answer: TODO
Evidence:

### Q23. What do we reuse or integrate?
Answer: TODO
Evidence:

### Q24. What standards do we implement?
Answer: TODO
Evidence:

### Q25. What are the hard platform boundaries — what will we never build?
Answer: TODO
Evidence:

---

## The closing statement

The teardown has succeeded when this can be written with confidence, backed by
evidence rather than taste. Draft it here; it becomes the opening of the v0.1
architecture document.

> TODO
