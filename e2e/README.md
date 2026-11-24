# Browser end-to-end test

Clicks through the real dashboard in Chrome: approve/deny, mine rules, accept, auto-approval with receipt, "Wrong" pauses the rule, hard lines, insights, audit, phone width, no JS errors.

```bash
cd engine && uv run yesrule demo && uv run yesrule serve --port 8790   # then post two pending requests
cd e2e && npm i && BASE=http://localhost:8790 npm test
```
Set CHROME_PATH if Chrome is not at the default macOS location.
