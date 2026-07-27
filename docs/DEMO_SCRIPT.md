# Demo Video Script

Record against the live deployed URL, not localhost. A screen recording with voiceover or captions is enough.

| Time | Beat |
| --- | --- |
| 0:00-0:15 | Show the landing page. Say: "This is a multi-agent housing decision system with dynamic routing and explicit trade-offs, not a chatbot wrapper." |
| 0:15-0:45 | Sign in and submit a full request: budget, UT Austin anchor, max commute, laundry, pet-friendly, safe/quiet, and scam concern. Show the live graph running planner, listing search, parallel specialists, critic, and recommendation. |
| 0:45-1:15 | Submit a minimal request, such as "anything under $1200 near downtown." Show the shorter execution graph. This is the key proof of dynamic routing. |
| 1:15-1:45 | Show results: ranked cards, trade-off narrative, comparison table, and map pins. Point out a constraint-risk badge if one appears naturally. |
| 1:45-2:05 | Show observability: real latency/cost charts and stale-pending visibility. |
| 2:05-2:20 | Show eval numbers: routing F1 0.9922, constraint match 0.8750, judge score 3.63 / 5. |
| 2:20-2:30 | Show GitHub repo and `v1.0` tag after release. |

Suggested demo requests:

```text
Full: I need a pet-friendly apartment under $1200 near UT Austin, max 20 minute walk, laundry required. I care about safe and quiet neighborhoods and I am worried about scammy below-market listings.
```

```text
Minimal: Show me anything under $1200 near downtown Austin.
```

After recording, add the public video link to the README live demo section.
