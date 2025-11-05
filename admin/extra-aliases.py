#!/usr/bin/env python3
"""
# parameters

Accepts in argv: USER HOST PORT IP DELETE
USER is required, others are optionals

CURRENT_IP is the first IP returned by hostname -I
Find the CURRENT_INTERFACE and CURRENT_NETMASK from the CURRENT_IP
Read the CURRENT_APIHOST from cm/config metadata.annotations.apihost
The USER_APIHOST is the CURRENT_APIHOST with added in the doman part the user 
(example: CURRENT_APIHOST is http://miniops.me the USER_APIHOST is http://devel.miniops.me)

If IP is empty defaults to CURRENT_IP
If HOST is empty defaults to the IP
if PORT is empty defaults to 80
DELETE is false by default

# Samples:

"test" "" "" "" ""
=> USER=test HOST=CURRENT_IP PORT=80 IP=CURRENT_IP DELETE=false
"test" "" "" "NEW_IP"  ""
=> USER=test HOST=NEW_IP port=80 ip=NEW_IP DELETE=false
"test" "NEW_HOST" "" "" ""
=> USER=test HOST=NEW_HOST port=80 ip=CURRENT_IP DELETE=false
"test" "NEW_HOST" "" "" ""
=> USER=test HOST=NEW_HOST port=80 ip=CURRENT_IP DELETE=false
"test" "" "8080" "" ""
=> USER=test HOST=CURENT_IP port=8080 ip=CURRENT_IP DELETE=false

# preflight test
- check you are running in ubuntu/debiano linux
- check netplan is available
- check nginx is installed, if not try to install it with sudo
- check you can read and are available in namespace nuvolaris the ingresses:
<USER>-apihost-api-ingress
<USER>-apihost-my-api-ingress
<USER>-static-ingress

# Immplementation (if DELETE is false)

# add alias if required
if CURRENT_IP != IP create an alias, adding /etc/netplan/50-IP.yanl
with

```
network:
  ethernets:
    <CURRENT_INTERFACE>
      addresses:
        - <IP>/<CURRENT_NETMASK>
```
then use sudo neplan apply

# add proxy if required (delete is false)

if PORT != 80 add /etc/nginx/sites-available/<HOST>-<PORT>

```
server {
    listen <PORT>;
    server_name <HOST>;

    location / {
        proxy_pass http://127.0.0.1:80;
        proxy_set_header Host <USER_APIHOST>;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Port <PORT>;
    }
}
```

Create a link from sites-enabled sites-available

Enable and start nginx

# Duplicate the ingress rules (delete is false)

For each of those ingresses
<USER>-apihost-api-ingress
<USER>-apihost-my-api-ingress
<USER>-static-ingress

1. read it
2. remove:
	•	metadata.name (give it a new name, unless you enjoy collisions)
	•	metadata.uid
	•	metadata.resourceVersion
	•	metadata.generation
	•	metadata.creationTimestamp
	•	the whole status: section
    -   metadata.annotations.kubectl.kubernetes.io/last-applied-configuration
3. replace spec.rules[0].host with <HOST> (port routing is handled by nginx proxy)
4. change the name to alias-<HOST>-<PORT>-<CURRENT_NAME> (replace '.' in '-')
5. apply it

# deleting

if DELETE is true,
- remove  /etc/nginx/sites-available/<HOST>-<PORT> if any
- remove etc/netplan/50-IP.yanl  if any
- remove each of those ingresses
alias-<HOST>-<PORT>-<USER>-apihost-api-ingress
alias-<HOST>-<PORT>-<USER>-apihost-my-api-ingress
alias-<HOST>-<PORT>-<USER>-static-ingress


If the env var DRY is set, 
will print the commands that changes state 
(can execute commands that reads, like kubectl get) 
and the files to be applied
(can actually write temp files )
instead of actually writing and running them.
Show the full file generated.
If you cannot execute a read command 
you should report the error and terminate.
"""

import sys
import subprocess
import os
import json
import yaml
from pathlib import Path

# Check if DRY run mode is enabled
DRY_RUN = os.environ.get('DRY', '').lower() in ['1', 'true', 'yes']

if DRY_RUN:
    print("=" * 60)
    print("DRY RUN MODE ENABLED - No actual changes will be made")
    print("=" * 60)
    print()


def run_command(cmd, check=True, capture_output=True):
    """Run a shell command and return the result."""
    # List of read-only command patterns that should execute even in DRY_RUN
    read_only_patterns = [
        'kubectl get',
        'kubectl describe',
        'hostname -I',
        'ip -j addr show',
        'which ',
    ]

    # Check if this is a read-only command
    is_read_only = any(pattern in cmd for pattern in read_only_patterns)

    if DRY_RUN and not is_read_only:
        print(f"[DRY RUN] Would execute command:")
        print(f"  {cmd}")
        print()
        # Return a mock result for dry run
        class MockResult:
            def __init__(self):
                self.returncode = 0
                self.stdout = ""
                self.stderr = ""
        return MockResult()

    # Execute the command (either not in DRY_RUN or it's a read-only command)
    if DRY_RUN and is_read_only:
        print(f"[DRY RUN] Executing read-only command:")
        print(f"  {cmd}")
        print()

    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=capture_output,
        text=True,
        check=False
    )

    # In DRY_RUN mode, if a read-only command fails, report and terminate
    if DRY_RUN and is_read_only and result.returncode != 0:
        print(f"[DRY RUN ERROR] Read command failed: {cmd}")
        print(f"Error: {result.stderr}")
        print("Cannot continue without being able to read required data.")
        sys.exit(1)

    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\nError: {result.stderr}")
    return result


def write_file(file_path, content, use_sudo=False):
    """Write content to a file, with dry-run support.

    In DRY_RUN mode:
    - Temp files (/tmp/*) are actually written so they can be inspected
    - System files (requiring sudo) are NOT written, only displayed
    """
    is_temp_file = file_path.startswith('/tmp/')

    if DRY_RUN and not is_temp_file:
        # Don't write system files in dry-run mode
        print("=" * 80)
        print(f"WOULD WRITE FILE: {file_path}")
        if use_sudo:
            print("(requires sudo)")
        print("=" * 80)
        print(content)
        print("=" * 80)
        print()
        return

    if DRY_RUN and is_temp_file:
        # Actually write temp files in dry-run mode
        print("=" * 80)
        print(f"WRITING TEMP FILE: {file_path}")
        print("(this file is actually written for inspection)")
        print("=" * 80)

    try:
        with open(file_path, 'w') as f:
            f.write(content)
        if DRY_RUN and is_temp_file:
            print(f"✓ Temp file written: {file_path}")
            print(content)
            print("=" * 80)
            print()
    except PermissionError:
        if use_sudo:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
                temp_file = f.name
                f.write(content)
            run_command(f"sudo mv {temp_file} {file_path}")
        else:
            raise


def get_current_ip():
    """Get the first IP from hostname -I."""
    result = run_command("hostname -I")
    ips = result.stdout.strip().split()
    if not ips:
        if DRY_RUN:
            # Return a mock IP for dry run if command fails
            print("[DRY RUN] Using mock IP: 192.168.1.100")
            return "192.168.1.100"
        raise RuntimeError("Could not determine current IP address")
    return ips[0]


def get_network_info(ip):
    """Get network interface and netmask for the given IP."""
    result = run_command("ip -j addr show")

    try:
        interfaces = json.loads(result.stdout)
    except json.JSONDecodeError:
        if DRY_RUN:
            # Return mock network info for dry run if command fails
            print("[DRY RUN] Using mock network info: eth0, 24")
            return "eth0", 24
        raise RuntimeError("Could not parse network interface information")

    for iface in interfaces:
        if 'addr_info' in iface:
            for addr in iface['addr_info']:
                if addr.get('local') == ip:
                    return iface['ifname'], addr.get('prefixlen', 24)

    if DRY_RUN:
        # Return mock network info for dry run if IP not found
        print(f"[DRY RUN] IP {ip} not found, using mock network info: eth0, 24")
        return "eth0", 24
    raise RuntimeError(f"Could not find interface for IP {ip}")


def check_os():
    """Check if running on Ubuntu/Debian."""
    if not os.path.exists('/etc/debian_version'):
        raise RuntimeError("This script requires Ubuntu/Debian Linux")


def check_netplan():
    """Check if netplan is available."""
    result = run_command("which netplan", check=False)
    if result.returncode != 0:
        raise RuntimeError("netplan is not installed")


def get_current_apihost():
    """Read CURRENT_APIHOST from cm/config metadata.annotations.apihost."""
    result = run_command(
        "kubectl get cm config -n nuvolaris -o jsonpath='{.metadata.annotations.apihost}'",
        check=False
    )

    if result.returncode != 0 or not result.stdout.strip():
        if DRY_RUN:
            print("[DRY RUN] Could not fetch apihost from cm/config, using mock data")
            return "http://miniops.me"
        raise RuntimeError("Could not read apihost from cm/config in namespace nuvolaris")

    return result.stdout.strip()


def get_user_apihost(current_apihost, user):
    """Calculate USER_APIHOST by adding user to the domain part of CURRENT_APIHOST.

    Example:
        CURRENT_APIHOST = "http://miniops.me"
        user = "devel"
        USER_APIHOST = "http://devel.miniops.me"
    """
    # Parse the apihost to extract protocol and domain
    if '://' in current_apihost:
        protocol, domain = current_apihost.split('://', 1)
        # Remove any trailing slashes or paths
        domain = domain.split('/')[0]
        user_apihost = f"{protocol}://{user}.{domain}"
    else:
        # No protocol specified, just add user to domain
        domain = current_apihost.split('/')[0]
        user_apihost = f"{user}.{domain}"

    return user_apihost


def check_and_install_nginx():
    """Check if nginx is installed, try to install if not."""
    result = run_command("which nginx", check=False)
    if result.returncode != 0:
        print("nginx not found, attempting to install...")
        result = run_command("sudo apt-get update && sudo apt-get install -y nginx", check=False)
        if result.returncode != 0:
            raise RuntimeError("Failed to install nginx")
        print("nginx installed successfully")


def check_ingresses(user):
    """Check if required ingresses exist in namespace nuvolaris."""
    ingress_names = [
        f"{user}-apihost-api-ingress",
        f"{user}-apihost-my-api-ingress",
        f"{user}-static-ingress"
    ]

    for ingress_name in ingress_names:
        result = run_command(
            f"kubectl get ingress {ingress_name} -n nuvolaris",
            check=False
        )
        if result.returncode != 0:
            raise RuntimeError(f"Required ingress {ingress_name} not found in namespace nuvolaris")


def preflight_checks(user):
    """Run all preflight checks."""
    if DRY_RUN:
        print("Skipping preflight checks in dry-run mode...")
        print()
        return

    print("Running preflight checks...")
    check_os()
    print("  OS check: OK")
    check_netplan()
    print("  netplan check: OK")
    check_and_install_nginx()
    print("  nginx check: OK")
    check_ingresses(user)
    print("  Ingress check: OK")
    print("All preflight checks passed!")


def create_network_alias(ip, current_ip, current_interface, current_netmask):
    """Create a network alias if IP differs from current IP."""
    if ip == current_ip:
        print(f"IP {ip} matches current IP, no alias needed")
        return

    netplan_file = f"/etc/netplan/50-{ip}.yaml"
    netplan_content = f"""network:
  ethernets:
    {current_interface}:
      addresses:
        - {ip}/{current_netmask}
"""

    # Write netplan file
    write_file(netplan_file, netplan_content, use_sudo=True)
    if not DRY_RUN:
        print(f"Created netplan file: {netplan_file}")

    # Apply netplan
    run_command("sudo netplan apply")
    if not DRY_RUN:
        print(f"Applied network alias for IP {ip}")


def create_nginx_proxy(host, port, user_apihost):
    """Create nginx proxy configuration if port is not 80."""
    if port == 80:
        print("Port is 80, no nginx proxy needed")
        return

    config_name = f"{host}-{port}"
    config_path = f"/etc/nginx/sites-available/{config_name}"
    enabled_path = f"/etc/nginx/sites-enabled/{config_name}"

    nginx_config = f"""server {{
    listen {port};
    server_name {host};

    location / {{
        proxy_pass http://127.0.0.1:80;
        proxy_set_header Host {user_apihost};
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Port {port};
    }}
}}
"""

    # Write nginx config
    write_file(config_path, nginx_config, use_sudo=True)
    if not DRY_RUN:
        print(f"Created nginx config: {config_path}")

    # Create symlink
    if DRY_RUN or not os.path.exists(enabled_path):
        run_command(f"sudo ln -s {config_path} {enabled_path}")
        if not DRY_RUN:
            print(f"Enabled nginx site: {config_name}")

    # Enable and start nginx
    run_command("sudo systemctl enable nginx", check=False)
    run_command("sudo systemctl start nginx", check=False)
    run_command("sudo systemctl reload nginx")
    if not DRY_RUN:
        print("nginx reloaded")


def duplicate_ingress(user, host, port, ingress_suffix):
    """Duplicate a Kubernetes ingress with new host and name."""
    original_name = f"{user}-{ingress_suffix}"
    # Replace dots with dashes in the new name to avoid collisions
    new_name = f"alias-{host}-{port}-{original_name}".replace('.', '-')

    # Get original ingress (this will execute even in DRY_RUN mode)
    result = run_command(f"kubectl get ingress {original_name} -n nuvolaris -o yaml", check=False)

    if result.returncode != 0 or not result.stdout.strip():
        if DRY_RUN:
            # In dry run mode, create a mock ingress structure if kubectl get fails
            print(f"[DRY RUN] Could not fetch ingress {original_name}, using mock data")
            ingress = {
                'apiVersion': 'networking.k8s.io/v1',
                'kind': 'Ingress',
                'metadata': {
                    'name': original_name,
                    'namespace': 'nuvolaris',
                    'uid': 'mock-uid',
                    'resourceVersion': 'mock-version',
                    'generation': 1,
                    'creationTimestamp': '2025-01-01T00:00:00Z'
                },
                'spec': {
                    'ingressClassName': 'nginx',
                    'rules': [{
                        'host': 'original-host.example.com',
                        'http': {
                            'paths': [{
                                'path': '/',
                                'pathType': 'Prefix',
                                'backend': {
                                    'service': {
                                        'name': 'example-service',
                                        'port': {'number': 80}
                                    }
                                }
                            }]
                        }
                    }]
                },
                'status': {}
            }
        else:
            raise RuntimeError(f"Could not fetch ingress {original_name}")
    else:
        ingress = yaml.safe_load(result.stdout)

    # Remove metadata fields
    fields_to_remove = ['uid', 'resourceVersion', 'generation', 'creationTimestamp']
    for field in fields_to_remove:
        ingress['metadata'].pop(field, None)

    # Remove last-applied-configuration annotation
    if 'annotations' in ingress['metadata']:
        ingress['metadata']['annotations'].pop('kubectl.kubernetes.io/last-applied-configuration', None)
        # Clean up empty annotations dict
        if not ingress['metadata']['annotations']:
            ingress['metadata'].pop('annotations', None)

    # Remove status section
    ingress.pop('status', None)

    # Update name
    ingress['metadata']['name'] = new_name

    # Update host in rules
    # Note: Ingress host field should only contain hostname, not port
    # Port routing is handled by the nginx proxy configured on the host
    if 'rules' in ingress['spec'] and len(ingress['spec']['rules']) > 0:
        ingress['spec']['rules'][0]['host'] = host

    # Apply the new ingress
    temp_file = f"/tmp/{new_name}.yaml"
    ingress_yaml = yaml.dump(ingress)

    # Write the ingress file (will actually write temp file even in dry-run mode)
    write_file(temp_file, ingress_yaml, use_sudo=False)

    run_command(f"kubectl apply -f {temp_file} -n nuvolaris")

    if not DRY_RUN:
        os.remove(temp_file)
        print(f"Created ingress: {new_name}")
    else:
        print(f"[DRY RUN] Temp file kept for inspection: {temp_file}")


def duplicate_ingresses(user, host, port):
    """Duplicate all required ingresses."""
    ingress_suffixes = [
        "apihost-api-ingress",
        "apihost-my-api-ingress",
        "static-ingress"
    ]

    for suffix in ingress_suffixes:
        duplicate_ingress(user, host, port, suffix)


def delete_network_alias(ip):
    """Remove network alias configuration."""
    netplan_file = f"/etc/netplan/50-{ip}.yaml"
    if DRY_RUN or os.path.exists(netplan_file):
        run_command(f"sudo rm {netplan_file}")
        run_command("sudo netplan apply")
        if not DRY_RUN:
            print(f"Removed network alias: {netplan_file}")
    else:
        print(f"Network alias file not found: {netplan_file}")


def delete_nginx_proxy(host, port):
    """Remove nginx proxy configuration."""
    config_name = f"{host}-{port}"
    config_path = f"/etc/nginx/sites-available/{config_name}"
    enabled_path = f"/etc/nginx/sites-enabled/{config_name}"

    if DRY_RUN or os.path.exists(enabled_path):
        run_command(f"sudo rm {enabled_path}")
        if not DRY_RUN:
            print(f"Removed nginx enabled site: {enabled_path}")

    if DRY_RUN or os.path.exists(config_path):
        run_command(f"sudo rm {config_path}")
        run_command("sudo systemctl reload nginx", check=False)
        if not DRY_RUN:
            print(f"Removed nginx config: {config_path}")
    else:
        print(f"nginx config not found: {config_path}")


def delete_ingress(user, host, port, ingress_suffix):
    """Delete a duplicated Kubernetes ingress."""
    original_name = f"{user}-{ingress_suffix}"
    # Replace dots with dashes in the ingress name to match creation convention
    ingress_name = f"alias-{host}-{port}-{original_name}".replace('.', '-')

    result = run_command(
        f"kubectl delete ingress {ingress_name} -n nuvolaris",
        check=False
    )
    if not DRY_RUN:
        if result.returncode == 0:
            print(f"Deleted ingress: {ingress_name}")
        else:
            print(f"Ingress not found: {ingress_name}")


def delete_ingresses(user, host, port):
    """Delete all duplicated ingresses."""
    ingress_suffixes = [
        "apihost-api-ingress",
        "apihost-my-api-ingress",
        "static-ingress"
    ]

    for suffix in ingress_suffixes:
        delete_ingress(user, host, port, suffix)


def main():
    # Parse arguments
    if len(sys.argv) < 2:
        print("Usage: add-aliases.py USER [HOST] [PORT] [IP] [DELETE]")
        sys.exit(1)

    user = sys.argv[1]

    # Get current network info
    current_ip = get_current_ip()
    current_interface, current_netmask = get_network_info(current_ip)

    # Get apihost info
    current_apihost = get_current_apihost()
    user_apihost = get_user_apihost(current_apihost, user)

    # Set defaults
    ip = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else current_ip
    host = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else ip
    port = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else 80
    delete = sys.argv[5].lower() in ['true', '1', 'yes'] if len(sys.argv) > 5 and sys.argv[5] else False

    print(f"Configuration:")
    print(f"  USER: {user}")
    print(f"  HOST: {host}")
    print(f"  PORT: {port}")
    print(f"  IP: {ip}")
    print(f"  DELETE: {delete}")
    print(f"  CURRENT_IP: {current_ip}")
    print(f"  CURRENT_INTERFACE: {current_interface}")
    print(f"  CURRENT_NETMASK: {current_netmask}")
    print(f"  CURRENT_APIHOST: {current_apihost}")
    print(f"  USER_APIHOST: {user_apihost}")
    print()
    

    # Run preflight checks (skip for delete operations)
    if not delete:
        preflight_checks(user)
        print()

    if delete:
        print("Deleting configuration...")
        delete_nginx_proxy(host, port)
        delete_network_alias(ip)
        delete_ingresses(user, host, port)
        print("Deletion complete!")
    else:
        print("Creating configuration...")
        create_network_alias(ip, current_ip, current_interface, current_netmask)
        create_nginx_proxy(host, port, user_apihost)
        duplicate_ingresses(user, host, port)
        print("Configuration complete!")
        print()
        print(f"Your application should now be accessible at {host}:{port}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

"""
# only ingress
DRY=1 ops admin extraingress devel  2>&1 | tee test1
# ingress and forward
DRY=1 ops admin extraingress devel --port=8080  2>&1 | tee test2
# ingress and alias
DRY=1 ops admin extraingress devel --ip=192.168.1.99 2>&1 | tee test3
# host
DRY=1 ops admin extraingress devel --host=devel.spark.n7s.co 2>&1 | tee test4
# host & port
DRY=1 ops admin extraingress devel --host=devel.spark.n7s.co --port=8080 2>&1 | tee test4
# host & ip
DRY=1 ops admin extraingress devel --host=devel.spark.n7s.co --ip=192.168.1.99 2>&1 | tee test4
# host & ip & port
DRY=1 ops admin extraingress devel  --port=8080 --host=devel.spark.n7s.co --ip=192.168.1.99 2>&1 | tee test4
# ip & port
DRY=1 ops admin extraingress devel  --port=8080  --ip=192.168.1.99 2>&1 | tee test4


| tee test1

grep "host: 192.168.1.100" test1


| tee test2


grep 'server_name 102.168.1.100' test2

DRY=1 ops admin extraingress devel --ip=192.168.1.101

"""