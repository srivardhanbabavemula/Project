#!/bin/bash

# =====================================================
# AWS Deployment Script (Free Tier)
# =====================================================

set -e

echo "=========================================="
echo "Deploying Fraud Detection to AWS Free Tier"
echo "=========================================="

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo "Error: AWS CLI not found. Please install it first."
    exit 1
fi

# Configuration
AWS_REGION=${AWS_REGION:-us-east-1}
APP_NAME="fraud-detection"
EC2_INSTANCE_TYPE="t2.micro"  # Free tier
RDS_INSTANCE_TYPE="db.t2.micro"  # Free tier

echo ""
echo "Configuration:"
echo "  Region: $AWS_REGION"
echo "  App Name: $APP_NAME"
echo "  EC2 Instance: $EC2_INSTANCE_TYPE"
echo "  RDS Instance: $RDS_INSTANCE_TYPE"
echo ""

# Create key pair if doesn't exist
echo "1. Checking SSH key pair..."
if ! aws ec2 describe-key-pairs --key-names ${APP_NAME}-key --region $AWS_REGION > /dev/null 2>&1; then
    echo "Creating key pair..."
    aws ec2 create-key-pair \
        --key-name ${APP_NAME}-key \
        --query 'KeyMaterial' \
        --output text \
        --region $AWS_REGION > ~/.ssh/${APP_NAME}-key.pem
    chmod 400 ~/.ssh/${APP_NAME}-key.pem
    echo "Key pair created: ~/.ssh/${APP_NAME}-key.pem"
else
    echo "Key pair already exists"
fi

# Create security group
echo ""
echo "2. Setting up security group..."
SG_ID=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=${APP_NAME}-sg" \
    --query "SecurityGroups[0].GroupId" \
    --output text \
    --region $AWS_REGION 2>/dev/null || echo "")

if [ "$SG_ID" = "" ] || [ "$SG_ID" = "None" ]; then
    echo "Creating security group..."
    SG_ID=$(aws ec2 create-security-group \
        --group-name ${APP_NAME}-sg \
        --description "Security group for fraud detection system" \
        --region $AWS_REGION \
        --query 'GroupId' \
        --output text)
    
    # Add inbound rules
    aws ec2 authorize-security-group-ingress \
        --group-id $SG_ID \
        --protocol tcp \
        --port 22 \
        --cidr 0.0.0.0/0 \
        --region $AWS_REGION
    
    aws ec2 authorize-security-group-ingress \
        --group-id $SG_ID \
        --protocol tcp \
        --port 8000 \
        --cidr 0.0.0.0/0 \
        --region $AWS_REGION
    
    echo "Security group created: $SG_ID"
else
    echo "Security group already exists: $SG_ID"
fi

# Launch EC2 instance
echo ""
echo "3. Launching EC2 instance..."
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id ami-0c55b159cbfafe1f0 \
    --instance-type $EC2_INSTANCE_TYPE \
    --key-name ${APP_NAME}-key \
    --security-group-ids $SG_ID \
    --region $AWS_REGION \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${APP_NAME}}]" \
    --user-data file://scripts/ec2_user_data.sh \
    --query 'Instances[0].InstanceId' \
    --output text)

echo "EC2 instance launching: $INSTANCE_ID"
echo "Waiting for instance to be running..."
aws ec2 wait instance-running --instance-ids $INSTANCE_ID --region $AWS_REGION

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids $INSTANCE_ID \
    --region $AWS_REGION \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Instance ID: $INSTANCE_ID"
echo "Public IP:   $PUBLIC_IP"
echo ""
echo "Wait 5-10 minutes for installation to complete, then access:"
echo "  API: http://$PUBLIC_IP:8000/docs"
echo ""
echo "SSH access:"
echo "  ssh -i ~/.ssh/${APP_NAME}-key.pem ec2-user@$PUBLIC_IP"
echo ""
echo "To terminate:"
echo "  aws ec2 terminate-instances --instance-ids $INSTANCE_ID --region $AWS_REGION"
echo "=========================================="
