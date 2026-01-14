#!/usr/bin/env python3
"""
EC2 Fleet Launcher for Rate Limit Testing

Launches multiple EC2 instances, deploys test scripts, runs tests in parallel,
and streams results to CloudWatch Logs for analysis.

Usage:
    python scripts/fleet_launcher.py --count 5              # Launch 5 instances
    python scripts/fleet_launcher.py --count 3 --interval 2 # 3 instances, 2s interval
    python scripts/fleet_launcher.py --cleanup              # Terminate all fleet instances
"""
import boto3
import time
import json
import sys
import argparse
import subprocess
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

# Configuration
REGION = "us-east-1"
INSTANCE_TYPE = "t2.micro"
AMI_ID = "ami-0453ec754f44f9a4a"  # Amazon Linux 2023
SSH_USER = "ec2-user"
KEY_NAME = "resy-sniper"
SECURITY_GROUP_NAME = "resy-sniper-sg"
LOG_GROUP_NAME = "/resy-sniper/rate-tests"
INSTANCE_PROFILE_NAME = "resy-sniper-cloudwatch-profile"
ROLE_NAME = "resy-sniper-cloudwatch-role"

# Paths
SCRIPT_DIR = Path(__file__).parent
KEY_PATH = Path.home() / ".ssh" / f"{KEY_NAME}.pem"
RATE_TEST_SCRIPT = SCRIPT_DIR / "rate_test_runner.sh"


def get_ec2_client():
    return boto3.client("ec2", region_name=REGION)


def get_ec2_resource():
    return boto3.resource("ec2", region_name=REGION)


def get_logs_client():
    return boto3.client("logs", region_name=REGION)


def get_iam_client():
    return boto3.client("iam")


def ensure_log_group():
    """Create CloudWatch log group if it doesn't exist."""
    logs = get_logs_client()
    try:
        logs.create_log_group(logGroupName=LOG_GROUP_NAME)
        print(f"   Created log group: {LOG_GROUP_NAME}")
    except logs.exceptions.ResourceAlreadyExistsException:
        print(f"   Log group exists: {LOG_GROUP_NAME}")


def ensure_instance_profile():
    """Create IAM role and instance profile for CloudWatch access."""
    iam = get_iam_client()
    
    # Trust policy for EC2
    trust_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    })
    
    # Check if role exists
    try:
        iam.get_role(RoleName=ROLE_NAME)
        print(f"   IAM role exists: {ROLE_NAME}")
    except iam.exceptions.NoSuchEntityException:
        print(f"   Creating IAM role: {ROLE_NAME}")
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=trust_policy,
            Description="Allows EC2 instances to write to CloudWatch Logs"
        )
        # Attach CloudWatch policy
        iam.attach_role_policy(
            RoleName=ROLE_NAME,
            PolicyArn="arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
        )
        time.sleep(2)  # Wait for role to propagate
    
    # Check if instance profile exists
    try:
        iam.get_instance_profile(InstanceProfileName=INSTANCE_PROFILE_NAME)
        print(f"   Instance profile exists: {INSTANCE_PROFILE_NAME}")
    except iam.exceptions.NoSuchEntityException:
        print(f"   Creating instance profile: {INSTANCE_PROFILE_NAME}")
        iam.create_instance_profile(InstanceProfileName=INSTANCE_PROFILE_NAME)
        iam.add_role_to_instance_profile(
            InstanceProfileName=INSTANCE_PROFILE_NAME,
            RoleName=ROLE_NAME
        )
        print("   Waiting for instance profile to propagate...")
        time.sleep(10)  # IAM takes time to propagate
    
    return INSTANCE_PROFILE_NAME


def get_security_group_id():
    """Get existing security group ID."""
    ec2 = get_ec2_client()
    try:
        response = ec2.describe_security_groups(GroupNames=[SECURITY_GROUP_NAME])
        return response["SecurityGroups"][0]["GroupId"]
    except:
        raise Exception(f"Security group '{SECURITY_GROUP_NAME}' not found. Run ec2_launcher.py first.")


def get_user_data_script(interval: int):
    """Bootstrap script that installs CloudWatch agent and runs test."""
    return f"""#!/bin/bash
set -e

# Install CloudWatch agent
yum install -y amazon-cloudwatch-agent

# Configure CloudWatch agent to stream stdout
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << 'EOF'
{{
    "logs": {{
        "logs_collected": {{
            "files": {{
                "collect_list": [
                    {{
                        "file_path": "/var/log/rate-test.log",
                        "log_group_name": "{LOG_GROUP_NAME}",
                        "log_stream_name": "{{instance_id}}",
                        "timestamp_format": "%Y-%m-%dT%H:%M:%S"
                    }}
                ]
            }}
        }}
    }}
}}
EOF

# Start CloudWatch agent
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json

# Create rate test script
cat > /home/ec2-user/rate_test.sh << 'SCRIPT'
#!/bin/bash
VENUE_ID=2492
TEST_DATE=2026-02-15
PARTY_SIZE=2
INTERVAL={interval}
MAX_REQUESTS=100
API_KEY="VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"

INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)

log_json() {{
    local req=$1 status=$2 latency=$3 blocked=$4
    echo "{{\\"instance_id\\":\\"$INSTANCE_ID\\",\\"ip\\":\\"$PUBLIC_IP\\",\\"request\\":$req,\\"status\\":$status,\\"latency_ms\\":$latency,\\"blocked\\":$blocked,\\"timestamp\\":\\"$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)\\"}}"
}}

echo "{{\\"instance_id\\":\\"$INSTANCE_ID\\",\\"ip\\":\\"$PUBLIC_IP\\",\\"event\\":\\"start\\",\\"interval\\":$INTERVAL,\\"timestamp\\":\\"$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)\\"}}"

for i in $(seq 1 $MAX_REQUESTS); do
    start=$(date +%s%3N)
    status=$(curl -s -o /dev/null -w "%{{http_code}}" \\
        "https://api.resy.com/4/find?lat=0&long=0&day=$TEST_DATE&party_size=$PARTY_SIZE&venue_id=$VENUE_ID" \\
        -H "Authorization: ResyAPI api_key=\\"$API_KEY\\"" \\
        --connect-timeout 10 --max-time 15)
    end=$(date +%s%3N)
    latency=$((end - start))
    
    if [ "$status" != "200" ]; then
        log_json $i $status $latency true
        break
    fi
    log_json $i $status $latency false
    sleep $INTERVAL
done

echo "{{\\"instance_id\\":\\"$INSTANCE_ID\\",\\"ip\\":\\"$PUBLIC_IP\\",\\"event\\":\\"complete\\",\\"total_requests\\":$i,\\"timestamp\\":\\"$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)\\"}}"
SCRIPT

chmod +x /home/ec2-user/rate_test.sh
chown ec2-user:ec2-user /home/ec2-user/rate_test.sh

# Wait a moment for CloudWatch agent to be ready
sleep 5

# Run the test, output to log file for CloudWatch
/home/ec2-user/rate_test.sh > /var/log/rate-test.log 2>&1

# Signal completion
echo "TEST_COMPLETE" >> /var/log/rate-test.log
"""


def launch_fleet(count: int, interval: int) -> list:
    """Launch multiple EC2 instances."""
    print(f"\n[1] Setting up prerequisites...")
    ensure_log_group()
    instance_profile = ensure_instance_profile()
    sg_id = get_security_group_id()
    
    print(f"\n[2] Launching {count} instances...")
    
    ec2 = get_ec2_resource()
    
    instances = ec2.create_instances(
        ImageId=AMI_ID,
        InstanceType=INSTANCE_TYPE,
        KeyName=KEY_NAME,
        SecurityGroupIds=[sg_id],
        IamInstanceProfile={"Name": instance_profile},
        MinCount=count,
        MaxCount=count,
        UserData=get_user_data_script(interval),
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [
                {"Key": "Name", "Value": "resy-fleet-tester"},
                {"Key": "Project", "Value": "resy-sniper"},
                {"Key": "Fleet", "Value": "rate-limit-test"}
            ]
        }]
    )
    
    instance_ids = [i.id for i in instances]
    print(f"   Launched: {', '.join(instance_ids)}")
    
    # Wait for all instances to be running
    print(f"\n[3] Waiting for instances to start...")
    ec2_client = get_ec2_client()
    
    waiter = ec2_client.get_waiter('instance_running')
    waiter.wait(InstanceIds=instance_ids)
    
    # Get instance details
    response = ec2_client.describe_instances(InstanceIds=instance_ids)
    fleet = []
    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
            fleet.append({
                "instance_id": instance["InstanceId"],
                "public_ip": instance.get("PublicIpAddress", "pending"),
                "state": instance["State"]["Name"]
            })
            print(f"   {instance['InstanceId']}: {instance.get('PublicIpAddress', 'pending')} [{instance['State']['Name']}]")
    
    return fleet


def monitor_cloudwatch(duration_minutes: int = 10):
    """Monitor CloudWatch logs for test results."""
    logs = get_logs_client()
    
    print(f"\n[4] Monitoring CloudWatch logs...")
    print("=" * 70)
    
    start_time = int((datetime.utcnow() - timedelta(minutes=1)).timestamp() * 1000)
    seen_events = set()
    results = {}
    complete_count = 0
    
    end_time = datetime.utcnow() + timedelta(minutes=duration_minutes)
    
    while datetime.utcnow() < end_time:
        try:
            response = logs.filter_log_events(
                logGroupName=LOG_GROUP_NAME,
                startTime=start_time,
                limit=100
            )
            
            for event in response.get("events", []):
                event_id = event["eventId"]
                if event_id in seen_events:
                    continue
                seen_events.add(event_id)
                
                message = event["message"].strip()
                stream = event["logStreamName"]
                
                # Parse JSON log
                try:
                    data = json.loads(message)
                    instance_id = data.get("instance_id", stream)
                    
                    if data.get("event") == "start":
                        print(f"[{instance_id[:10]}] Started - IP: {data.get('ip')}")
                        results[instance_id] = {"ip": data.get("ip"), "requests": 0, "blocked_at": None}
                    
                    elif data.get("event") == "complete":
                        results[instance_id]["requests"] = data.get("total_requests", 0)
                        complete_count += 1
                        print(f"[{instance_id[:10]}] COMPLETE - {data.get('total_requests')} requests")
                    
                    elif "request" in data:
                        req_num = data["request"]
                        status = data["status"]
                        if data.get("blocked"):
                            results[instance_id]["blocked_at"] = req_num
                            print(f"[{instance_id[:10]}] BLOCKED at request {req_num} (status {status})")
                        elif req_num % 10 == 0:  # Print every 10th request
                            print(f"[{instance_id[:10]}] Request {req_num}: {status}")
                
                except json.JSONDecodeError:
                    if "TEST_COMPLETE" in message:
                        complete_count += 1
            
        except Exception as e:
            print(f"   Log fetch error: {e}")
        
        time.sleep(2)
    
    return results


def print_summary(results: dict):
    """Print summary table of results."""
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    print(f"{'Instance':<20} {'IP':<16} {'Requests':<10} {'Blocked At':<10}")
    print("-" * 70)
    
    request_counts = []
    for instance_id, data in results.items():
        ip = data.get("ip", "N/A")
        requests = data.get("requests", 0)
        blocked_at = data.get("blocked_at", "N/A")
        if blocked_at:
            request_counts.append(blocked_at)
        print(f"{instance_id[:20]:<20} {ip:<16} {requests:<10} {blocked_at}")
    
    print("-" * 70)
    if request_counts:
        avg = sum(request_counts) / len(request_counts)
        min_val = min(request_counts)
        max_val = max(request_counts)
        print(f"Blocked at: avg={avg:.1f}, min={min_val}, max={max_val}")
    print("=" * 70)


def terminate_fleet():
    """Terminate all fleet instances."""
    ec2 = get_ec2_client()
    
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Fleet", "Values": ["rate-limit-test"]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}
        ]
    )
    
    instance_ids = []
    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
            instance_ids.append(instance["InstanceId"])
    
    if not instance_ids:
        print("No fleet instances found.")
        return
    
    print(f"Terminating {len(instance_ids)} instances...")
    ec2.terminate_instances(InstanceIds=instance_ids)
    print("Termination initiated.")


def main():
    parser = argparse.ArgumentParser(description='EC2 Fleet Rate Limit Tester')
    parser.add_argument('--count', type=int, default=5, help='Number of instances to launch')
    parser.add_argument('--interval', type=int, default=1, help='Seconds between requests')
    parser.add_argument('--cleanup', action='store_true', help='Terminate all fleet instances')
    parser.add_argument('--monitor-only', action='store_true', help='Only monitor CloudWatch (no launch)')
    args = parser.parse_args()
    
    if args.cleanup:
        terminate_fleet()
        return
    
    if args.monitor_only:
        results = monitor_cloudwatch(duration_minutes=15)
        print_summary(results)
        return
    
    print("=" * 70)
    print(f"RATE LIMIT FLEET TEST - {args.count} INSTANCES")
    print("=" * 70)
    print(f"   Instances:  {args.count}")
    print(f"   Interval:   {args.interval}s between requests")
    print(f"   Region:     {REGION}")
    print("=" * 70)
    
    try:
        # Launch fleet
        fleet = launch_fleet(args.count, args.interval)
        
        print("\n   Waiting 60 seconds for instances to initialize...")
        time.sleep(60)
        
        # Monitor results
        results = monitor_cloudwatch(duration_minutes=10)
        
        # Print summary
        print_summary(results)
        
    finally:
        # Always cleanup
        print("\n[5] Cleaning up...")
        terminate_fleet()
        print("Done.")


if __name__ == "__main__":
    main()
