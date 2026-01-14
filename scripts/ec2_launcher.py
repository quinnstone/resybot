#!/usr/bin/env python3
"""
EC2 Instance Launcher for Rate Limit Testing

Usage:
    python scripts/ec2_launcher.py launch          # Launch new instance
    python scripts/ec2_launcher.py status          # Check instance status
    python scripts/ec2_launcher.py ssh             # Print SSH command
    python scripts/ec2_launcher.py terminate       # Terminate instance
    python scripts/ec2_launcher.py list            # List running instances
"""
import boto3
import time
import json
import sys
import os
from pathlib import Path

# Configuration
REGION = "us-east-1"
INSTANCE_TYPE = "t2.micro"  # Free tier eligible
AMI_ID = "ami-0453ec754f44f9a4a"  # Amazon Linux 2023 (us-east-1)
SSH_USER = "ec2-user"  # Amazon Linux uses ec2-user
KEY_NAME = "resy-sniper"  # Will create if doesn't exist
SECURITY_GROUP_NAME = "resy-sniper-sg"
INSTANCE_NAME = "resy-rate-limit-tester"

# Path to store instance info
STATE_FILE = Path(__file__).parent.parent / "config" / "ec2_state.json"


def get_ec2_client():
    return boto3.client("ec2", region_name=REGION)


def get_ec2_resource():
    return boto3.resource("ec2", region_name=REGION)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def ensure_key_pair(ec2_client):
    """Create key pair if it doesn't exist, save private key locally."""
    key_path = Path.home() / ".ssh" / f"{KEY_NAME}.pem"
    
    try:
        ec2_client.describe_key_pairs(KeyNames=[KEY_NAME])
        print(f"   Key pair '{KEY_NAME}' already exists")
        if not key_path.exists():
            print(f"   ⚠️  Warning: Key file not found at {key_path}")
            print(f"      You may need to recreate the key pair or find the .pem file")
        return KEY_NAME
    except ec2_client.exceptions.ClientError:
        pass
    
    print(f"   Creating key pair '{KEY_NAME}'...")
    response = ec2_client.create_key_pair(KeyName=KEY_NAME)
    
    # Save private key
    key_path.parent.mkdir(exist_ok=True)
    key_path.write_text(response["KeyMaterial"])
    key_path.chmod(0o400)
    print(f"   Private key saved to: {key_path}")
    
    return KEY_NAME


def ensure_security_group(ec2_client):
    """Create security group if it doesn't exist."""
    try:
        response = ec2_client.describe_security_groups(GroupNames=[SECURITY_GROUP_NAME])
        sg_id = response["SecurityGroups"][0]["GroupId"]
        print(f"   Security group '{SECURITY_GROUP_NAME}' already exists: {sg_id}")
        return sg_id
    except ec2_client.exceptions.ClientError:
        pass
    
    print(f"   Creating security group '{SECURITY_GROUP_NAME}'...")
    
    # Get default VPC
    vpcs = ec2_client.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])
    vpc_id = vpcs["Vpcs"][0]["VpcId"]
    
    response = ec2_client.create_security_group(
        GroupName=SECURITY_GROUP_NAME,
        Description="Security group for Resy rate limit testing",
        VpcId=vpc_id
    )
    sg_id = response["GroupId"]
    
    # Allow SSH from anywhere (you may want to restrict this)
    ec2_client.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {
                "IpProtocol": "tcp",
                "FromPort": 22,
                "ToPort": 22,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "SSH access"}]
            }
        ]
    )
    print(f"   Created security group: {sg_id}")
    return sg_id


def get_user_data_script():
    """Bootstrap script to set up the instance."""
    return """#!/bin/bash
set -e

# Update system
yum update -y

# Install Python 3 and pip
yum install -y python3 python3-pip git

# Install required packages
pip3 install requests python-dotenv boto3

# Create working directory
mkdir -p /home/ec2-user/resy-sniper
chown ec2-user:ec2-user /home/ec2-user/resy-sniper

echo "Setup complete!" > /home/ec2-user/setup_complete.txt
"""


def launch_instance():
    """Launch a new EC2 instance."""
    print("=" * 60)
    print("LAUNCHING EC2 INSTANCE")
    print("=" * 60)
    
    ec2_client = get_ec2_client()
    ec2 = get_ec2_resource()
    
    # Ensure prerequisites
    print("\n[1] Checking prerequisites...")
    key_name = ensure_key_pair(ec2_client)
    sg_id = ensure_security_group(ec2_client)
    
    # Launch instance
    print(f"\n[2] Launching instance...")
    print(f"   AMI:           {AMI_ID}")
    print(f"   Instance type: {INSTANCE_TYPE}")
    print(f"   Region:        {REGION}")
    
    instances = ec2.create_instances(
        ImageId=AMI_ID,
        InstanceType=INSTANCE_TYPE,
        KeyName=key_name,
        SecurityGroupIds=[sg_id],
        MinCount=1,
        MaxCount=1,
        UserData=get_user_data_script(),
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Name", "Value": INSTANCE_NAME},
                    {"Key": "Project", "Value": "resy-sniper"}
                ]
            }
        ]
    )
    
    instance = instances[0]
    print(f"   Instance ID:   {instance.id}")
    
    # Wait for instance to be running
    print(f"\n[3] Waiting for instance to start...")
    instance.wait_until_running()
    instance.reload()
    
    public_ip = instance.public_ip_address
    print(f"   Instance is running!")
    print(f"   Public IP:     {public_ip}")
    
    # Save state
    state = {
        "instance_id": instance.id,
        "public_ip": public_ip,
        "key_name": key_name,
        "launched_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    save_state(state)
    
    # Print connection info
    key_path = Path.home() / ".ssh" / f"{KEY_NAME}.pem"
    print(f"\n" + "=" * 60)
    print("INSTANCE READY")
    print("=" * 60)
    print(f"\nSSH command:")
    print(f"   ssh -i {key_path} {SSH_USER}@{public_ip}")
    print(f"\nTo copy files:")
    print(f"   scp -i {key_path} -r src/ sniper.py requirements.txt {SSH_USER}@{public_ip}:~/resy-sniper/")
    print(f"\nWait ~2 minutes for user-data script to complete setup.")
    
    return instance.id


def get_instance_status():
    """Get status of the managed instance."""
    state = load_state()
    if not state.get("instance_id"):
        print("No managed instance found. Run 'launch' first.")
        return None
    
    ec2_client = get_ec2_client()
    
    try:
        response = ec2_client.describe_instances(InstanceIds=[state["instance_id"]])
        instance = response["Reservations"][0]["Instances"][0]
        
        status = instance["State"]["Name"]
        public_ip = instance.get("PublicIpAddress", "N/A")
        
        print("=" * 60)
        print("INSTANCE STATUS")
        print("=" * 60)
        print(f"   Instance ID:   {state['instance_id']}")
        print(f"   Status:        {status}")
        print(f"   Public IP:     {public_ip}")
        print(f"   Launched:      {state.get('launched_at', 'Unknown')}")
        
        if status == "running":
            key_path = Path.home() / ".ssh" / f"{KEY_NAME}.pem"
            print(f"\nSSH command:")
            print(f"   ssh -i {key_path} {SSH_USER}@{public_ip}")
        
        return instance
        
    except Exception as e:
        print(f"Error getting status: {e}")
        return None


def print_ssh_command():
    """Print the SSH command for the current instance."""
    state = load_state()
    if not state.get("instance_id"):
        print("No managed instance found. Run 'launch' first.")
        return
    
    ec2_client = get_ec2_client()
    response = ec2_client.describe_instances(InstanceIds=[state["instance_id"]])
    instance = response["Reservations"][0]["Instances"][0]
    
    if instance["State"]["Name"] != "running":
        print(f"Instance is not running (state: {instance['State']['Name']})")
        return
    
    public_ip = instance.get("PublicIpAddress")
    key_path = Path.home() / ".ssh" / f"{KEY_NAME}.pem"
    
    print(f"ssh -i {key_path} {SSH_USER}@{public_ip}")


def terminate_instance():
    """Terminate the managed instance."""
    state = load_state()
    if not state.get("instance_id"):
        print("No managed instance found.")
        return
    
    ec2_client = get_ec2_client()
    instance_id = state["instance_id"]
    
    print(f"Terminating instance {instance_id}...")
    ec2_client.terminate_instances(InstanceIds=[instance_id])
    print("Instance termination initiated.")
    
    # Clear state
    save_state({})


def list_instances():
    """List all running instances with our tag."""
    ec2_client = get_ec2_client()
    
    response = ec2_client.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": ["resy-sniper"]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}
        ]
    )
    
    print("=" * 60)
    print("RESY SNIPER INSTANCES")
    print("=" * 60)
    
    instances = []
    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
            instances.append(instance)
            name = "unnamed"
            for tag in instance.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
            
            print(f"\n   {instance['InstanceId']}")
            print(f"      Name:   {name}")
            print(f"      State:  {instance['State']['Name']}")
            print(f"      IP:     {instance.get('PublicIpAddress', 'N/A')}")
            print(f"      Type:   {instance['InstanceType']}")
    
    if not instances:
        print("\n   No instances found.")
    
    return instances


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "launch":
        launch_instance()
    elif command == "status":
        get_instance_status()
    elif command == "ssh":
        print_ssh_command()
    elif command == "terminate":
        terminate_instance()
    elif command == "list":
        list_instances()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()