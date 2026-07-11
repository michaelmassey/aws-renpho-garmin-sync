#!/bin/bash

# Exit on error
set -e

echo "=========================================================="
echo " AWS Renpho-Garmin Sync: SSM Parameter Store Bootstrapper"
echo "=========================================================="
echo "This script will securely write your credentials directly to AWS Systems"
echo "Manager Parameter Store as encrypted SecureString parameters."
echo ""

# Get current AWS caller identity to verify session
if ! aws sts get-caller-identity --query "Arn" --output text > /dev/null 2>&1; then
    echo "Error: AWS CLI is not configured or your session has expired."
    echo "Please configure your AWS credentials (e.g. via 'aws configure') and try again."
    exit 1
fi

AWS_ACCOUNT=$(aws sts get-caller-identity --query "Account" --output text)
AWS_REGION=$(aws configure get region || echo "default region")

echo "Current AWS Context:"
echo "  - Account: $AWS_ACCOUNT"
echo "  - Region:  $AWS_REGION"
echo ""

# Prompt for values
read -p "Enter Renpho Email: " renpho_email

# Read password silently
echo -n "Enter Renpho Password: "
read -s renpho_password
echo ""

read -p "Enter Garmin Email: " garmin_email

echo -n "Enter Garmin Password: "
read -s garmin_password
echo ""
echo ""

echo "Writing parameters to SSM Parameter Store..."

# 1. Renpho Email
aws ssm put-parameter \
  --name "/renpho-garmin-sync/renpho_email" \
  --value "$renpho_email" \
  --type "SecureString" \
  --description "Renpho login email for weight sync tool" \
  --overwrite > /dev/null
echo "  ✔ Stored: /renpho-garmin-sync/renpho_email"

# 2. Renpho Password
aws ssm put-parameter \
  --name "/renpho-garmin-sync/renpho_password" \
  --value "$renpho_password" \
  --type "SecureString" \
  --description "Renpho login password for weight sync tool" \
  --overwrite > /dev/null
echo "  ✔ Stored: /renpho-garmin-sync/renpho_password"

# 3. Garmin Email
aws ssm put-parameter \
  --name "/renpho-garmin-sync/garmin_email" \
  --value "$garmin_email" \
  --type "SecureString" \
  --description "Garmin Connect login email for weight sync tool" \
  --overwrite > /dev/null
echo "  ✔ Stored: /renpho-garmin-sync/garmin_email"

# 4. Garmin Password
aws ssm put-parameter \
  --name "/renpho-garmin-sync/garmin_password" \
  --value "$garmin_password" \
  --type "SecureString" \
  --description "Garmin Connect login password for weight sync tool" \
  --overwrite > /dev/null
echo "  ✔ Stored: /renpho-garmin-sync/garmin_password"

echo ""
echo "Success! All four SecureString parameters have been successfully stored."
echo "You can now run 'cdk deploy' to deploy the infrastructure."
