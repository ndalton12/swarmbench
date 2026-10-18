# Keeping AWS costs bounded

AWS has no hard "stop spending at $X" switch: billing data lags by hours, and a budget never
shuts anything down by itself. What you can do is make large bills impossible or short-lived:
limit what can run at once, stop VMs that are idle or have run too long, and get warned
early. Set these up once, before the first launch. They cost nothing or nearly nothing (a
CloudWatch alarm is free for the first 10, then $0.10 a month each).

## 1. Limit how much can run at once (a hard limit)

**Service Quotas → Amazon EC2 → "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z)
instances"**, in the region you use (the files here assume us-east-1). Request exactly the vCPUs
of the largest VM you plan to run: **64** for one m7g.16xlarge. AWS then refuses any launch that
would take the running total over 64 vCPUs, whatever a script or a mistake asks for. (64 vCPUs
could also be several smaller VMs at once.) New accounts often start lower, so request it a day
ahead. AWS can raise quotas on its own for accounts with steady usage; check the number now and
then.

## 2. Use a limited IAM user for `deploy/aws.sh` (a hard limit)

Create an IAM user (or an SSO permission set) for the AWS CLI with only
`deploy/aws-iam-policy.json` attached (IAM → Policies → Create policy → JSON; then attach it
to the user and run `aws configure` with that user's access key). It allows:

- launching or restarting only m7g and r7g VMs (no GPUs, no other families), only in us-east-1;
- only plain gp3 disks of at most 500 GB each, with no paid extra speed;
- stopping and terminating only VMs tagged `swarmbench=1` (the ones the script makes);
- the SSH key pair, firewall and idle alarm the script uses (including, once, the role CloudWatch
  needs to stop a VM); nothing else, so no other services.

Stopped VMs keep their disks, which bill (about $0.08 per GB-month) even though they don't count
toward the vCPU quota: terminate VMs you won't use again (`deploy/aws.sh terminate`, after
`deploy/aws.sh fetch`).

To use another region, replace every `us-east-1` in the file. Don't use your root login for
the CLI.

## 3. VMs stop themselves when idle (automatic)

`deploy/aws.sh launch` sets this up on every VM, before anything else:

- the VM stops itself 120 minutes after its last swarmbench run, screen, experiment or judge
  ends and nobody has typed in a terminal (typing keeps it up for 30 minutes more, so the stop
  comes 2-2.5 hours after you leave). A forgotten `swarm view` or a tmux clock doesn't count.
- whatever is happening, it also stops 24 hours after each start, so even a stuck run or a
  workload that never ends can't bill for more than a day;
- a CloudWatch alarm stops it after 6 hours in which every hour had under 5 MB of network
  traffic, in case the VM itself is stuck. (CPU can't tell judging, which mostly waits for model
  APIs, from idle on a large VM; the prompts judging sends can.)

Change them at launch (`--idle-minutes N`, `--max-uptime-hours H`) or later on the VM in
`/etc/vm-idle-stop`; 0 turns one off (`--idle-minutes 0` also skips the alarm). For a run that
needs more than a day, raise the limit before starting it.

A stopped VM keeps its disk (about $24 a month for 300 GB) and costs nothing else.
`deploy/aws.sh start` brings it back.

## 4. Get warned, and block new launches at your limit (Budgets)

**Billing → Budgets → Create budget → Cost budget**, monthly, with the amount you're willing to
front (say $300):

- alerts by email at 50% and 80% of actual spend, and at 100% of forecast spend;
- an action at 100% of actual spend: **Apply IAM policy** `deploy/aws-deny-launch-policy.json`
  (create it as a policy first) to your CLI user, with **automatic** execution (otherwise it
  waits for your approval). It blocks new and restarted VMs; Budgets removes it when the next
  budget period starts. It doesn't stop a VM that is already running: the idle and uptime stops
  above do that. Budgets need a role allowed to attach it; the console offers to create one.

Budget numbers lag by several hours, so they're a backstop to steps 1-3, not a brake.

## 5. Catch surprises (Cost Anomaly Detection)

**Billing → Cost Anomaly Detection → Create monitor** (AWS services), with a daily email
summary.

## What the worst case looks like with all of this

At most 64 vCPUs running at once (step 1; one m7g.16xlarge is about $2.61 an hour), each VM
stopping 2-2.5 hours after work ends (about $6 of idle time) and at most 24 hours after it was
started (about $63), plus the disks of VMs you keep. A VM restarted again and again, or several
VMs launched under different names, multiply that, which is what the budget warnings are for.
Model spend (OpenRouter, Anthropic) is separate and larger: cap it with each run's `--max-cost`,
and set a credit limit on your OpenRouter key (OpenRouter → Keys → edit → credit limit).
