# AI Code Review Format Specification
## Version: 1.0.0
## Model: Qwen2.5-Coder (Local)
## Context Window: 32K tokens (manageable chunks)

---

## REVIEW STRUCTURE

Every code review MUST follow this exact JSON structure:

```json
{
  "review_metadata": {
    "review_id": "uuid-v4",
    "timestamp": "ISO-8601",
    "model": "qwen2.5-coder:7b",
    "pr_number": 123,
    "branch": "feature-branch-name",
    "commit_sha": "abc123...",
    "files_reviewed": 5,
    "total_lines_changed": 150
  },

  "summary": {
    "verdict": "APPROVE|REQUEST_CHANGES|COMMENT",
    "confidence_score": 0.85,
    "overall_assessment": "Brief 2-3 sentence summary",
    "risk_level": "LOW|MEDIUM|HIGH|CRITICAL",
    "estimated_review_time": "15 minutes"
  },

  "categories": {
    "critical_issues": [
      {
        "file": "src/auth.py",
        "line": 45,
        "severity": "CRITICAL",
        "category": "SECURITY",
        "title": "SQL Injection Vulnerability",
        "description": "User input directly concatenated into SQL query without parameterization",
        "current_code": "query = 'SELECT * FROM users WHERE id = ' + user_id",
        "suggested_fix": "query = 'SELECT * FROM users WHERE id = %s'; cursor.execute(query, (user_id,))",
        "impact": "Attackers can extract entire database or delete data",
        "cwe_id": "CWE-89",
        "fix_complexity": "EASY"
      }
    ],

    "important_issues": [
      {
        "file": "src/api.py",
        "line": 78,
        "severity": "HIGH",
        "category": "ERROR_HANDLING",
        "title": "Bare Exception Catching",
        "description": "Using bare 'except:' catches KeyboardInterrupt and SystemExit",
        "current_code": "except:",
        "suggested_fix": "except SpecificException as e:",
        "impact": "Can mask critical system signals and make debugging impossible",
        "cwe_id": "CWE-396",
        "fix_complexity": "EASY"
      }
    ],

    "suggestions": [
      {
        "file": "src/utils.py",
        "line": 23,
        "severity": "MEDIUM",
        "category": "PERFORMANCE",
        "title": "Inefficient List Concatenation",
        "description": "Using + to concatenate lists in loop creates O(n²) complexity",
        "current_code": "result = result + item",
        "suggested_fix": "result.append(item) or use list comprehension",
        "impact": "Performance degradation with large datasets",
        "fix_complexity": "EASY"
      }
    ],

    "positive_feedback": [
      {
        "file": "src/models.py",
        "line": 56,
        "category": "BEST_PRACTICE",
        "praise": "Excellent use of type hints and Pydantic validation",
        "context": "Class User(BaseModel): ..."
      }
    ]
  },

  "statistics": {
    "issues_by_severity": {
      "CRITICAL": 0,
      "HIGH": 2,
      "MEDIUM": 5,
      "LOW": 3
    },
    "issues_by_category": {
      "SECURITY": 1,
      "PERFORMANCE": 2,
      "MAINTAINABILITY": 3,
      "READABILITY": 2,
      "TESTING": 1,
      "DOCUMENTATION": 1
    },
    "code_quality_score": 7.5
  },

  "action_items": {
    "must_fix_before_merge": ["Issue #1", "Issue #2"],
    "should_fix_in_follow_up": ["Issue #3", "Issue #4"],
    "good_to_have": ["Issue #5"]
  },

  "educational_notes": [
    {
      "topic": "Python Context Managers",
      "explanation": "Consider using 'with' statement for resource management",
      "reference": "https://docs.python.org/3/reference/datamodel.html#context-managers"
    }
  ]
}
```

---

## REVIEW CATEGORIES & CHECKS

### 1. SECURITY (Critical Priority)
- [ ] Injection vulnerabilities (SQL, NoSQL, Command, LDAP)
- [ ] Authentication/Authorization flaws
- [ ] Sensitive data exposure (secrets, keys, PII)
- [ ] XXE, SSRF, CSRF vulnerabilities
- [ ] Insecure deserialization
- [ ] Security misconfigurations
- [ ] Using components with known vulnerabilities

### 2. ERROR HANDLING & LOGGING
- [ ] Bare except clauses
- [ ] Silent error swallowing
- [ ] Sensitive info in error messages
- [ ] Proper exception hierarchies
- [ ] Structured logging implementation

### 3. PERFORMANCE
- [ ] Algorithmic complexity (O(n²) in loops)
- [ ] N+1 query problems
- [ ] Memory leaks
- [ ] Unnecessary object creation
- [ ] Blocking I/O in async contexts
- [ ] Resource pool exhaustion

### 4. CODE QUALITY & MAINTAINABILITY
- [ ] Function length (>50 lines flag)
- [ ] Cyclomatic complexity (>10 flag)
- [ ] Duplicate code detection
- [ ] Dead code identification
- [ ] Proper abstraction layers
- [ ] SOLID principles adherence

### 5. TESTING
- [ ] Test coverage for new code
- [ ] Edge case handling
- [ ] Mock usage appropriateness
- [ ] Test data isolation
- [ ] Flaky test patterns

### 6. DOCUMENTATION
- [ ] Docstring completeness
- [ ] Complex logic explanation
- [ ] API documentation updates
- [ ] Changelog entries

---

## REVIEW DECISION MATRIX

| Criteria | APPROVE | REQUEST_CHANGES | COMMENT |
|----------|---------|-----------------|---------|
| Critical Issues | 0 | ≥1 | 0 |
| High Severity | ≤1 (with justification) | ≥2 | ≤2 |
| Test Coverage | ≥80% | <60% | 60-80% |
| Documentation | Complete | Missing critical | Minor gaps |
| Breaking Changes | None | Unhandled | Documented |

---

## DIFF ANALYSIS INSTRUCTIONS

When analyzing diffs:
1. **Focus ONLY on changed lines** (lines starting with + or -)
2. **Consider context** (3 lines before/after for understanding)
3. **Track line numbers** accurately for GitHub commenting
4. **Identify file types** and apply language-specific rules
5. **Batch related issues** to avoid comment spam

---

## COMMENT POSTING RULES

1. **CRITICAL/HIGH**: Inline comments on specific lines + Review summary
2. **MEDIUM**: Group by file, post as review comments
3. **LOW/Suggestions**: Single summary comment with list
4. **Positive feedback**: 1-2 comments max, genuine praise only
5. **Never repeat**: Same issue type in same function

---

## LANGUAGE-SPECIFIC NOTES

### Python
- Type hint coverage
- asyncio usage patterns
- Dataclass vs NamedTuple vs Pydantic
- Generator usage for large datasets

### JavaScript/TypeScript
- Promise/async-await patterns
- Type strictness (any usage)
- Memory leaks in closures
- React hook dependencies

### Java
- Null safety
- Stream API usage
- Exception handling hierarchies
- Resource try-with-resources

### Go
- Error handling (if err != nil patterns)
- Context propagation
- Goroutine leaks
- Interface design
