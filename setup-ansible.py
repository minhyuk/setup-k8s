#!/usr/bin/env python3

import argparse
import os
import subprocess
import sys
import socket
import paramiko
import yaml
from pathlib import Path
from typing import List, Dict, Optional
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

class AnsibleSetup:
    def __init__(self, master_ip: str, worker_ips: List[str], ssh_user: str = "ubuntu", ssh_password: Optional[str] = None):
        self.master_ip = master_ip
        self.worker_ips = worker_ips
        self.ssh_user = ssh_user
        self.ssh_password = ssh_password
        self.ssh_key_path = str(Path.home() / ".ssh" / "id_rsa")
        
        # 로깅 설정
        self.setup_logging()

    def setup_logging(self):
        """Configure logging"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('ansible_setup.log')
            ]
        )
        self.logger = logging.getLogger(__name__)

    def run_command(self, command: str, shell: bool = False) -> tuple:
        """Execute command locally"""
        try:
            result = subprocess.run(
                command if shell else command.split(),
                shell=shell,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return True, result.stdout
        except subprocess.CalledProcessError as e:
            return False, f"Error: {e.stderr}"

    def create_ssh_key(self) -> bool:
        """Generate SSH key (if not exists)"""
        if not os.path.exists(self.ssh_key_path):
            self.logger.info("Generating new SSH key pair...")
            cmd = f'ssh-keygen -t rsa -b 4096 -f {self.ssh_key_path} -N ""'
            success, output = self.run_command(cmd, shell=True)
            if not success:
                self.logger.error(f"Failed to generate SSH key: {output}")
                return False
        return True

    def get_ssh_client(self, host: str) -> paramiko.SSHClient:
        """Create SSH client"""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return client

    def execute_remote_command(self, client: paramiko.SSHClient, command: str) -> tuple:
        """Execute remote command"""
        try:
            if command.startswith('sudo') and self.ssh_password:
                command = f'echo {self.ssh_password} | sudo -S ' + command[5:]
            
            stdin, stdout, stderr = client.exec_command(command, get_pty=True)
            exit_status = stdout.channel.recv_exit_status()
            output = stdout.read().decode()
            error = stderr.read().decode()
            return exit_status == 0, output if exit_status == 0 else error
        except Exception as e:
            return False, str(e)

    def setup_node(self, host: str) -> bool:
        """Configure each node"""
        self.logger.info(f"Setting up node: {host}")
        client = self.get_ssh_client(host)
        
        try:
            # SSH 연결 시도 (키 기반, 비밀번호 기반 순서로)
            connected = False
            try:
                client.connect(host, username=self.ssh_user, key_filename=self.ssh_key_path)
                connected = True
            except:
                if self.ssh_password:
                    client.connect(host, username=self.ssh_user, password=self.ssh_password)
                    connected = True

            if not connected:
                self.logger.error(f"Could not connect to {host}")
                return False

            # 필요한 패키지 설치 전에 NOPASSWD 설정 추가
            commands = [
                "sudo apt-get update",
                "sudo apt-get install -y python3-pip sshpass",
                "pip3 install --user ansible",
                'echo "export PATH=$PATH:$HOME/.local/bin" >> ~/.bashrc',
                "source ~/.bashrc"
            ]

            for cmd in commands:
                success, output = self.execute_remote_command(client, cmd)
                if not success:
                    self.logger.error(f"Failed to execute '{cmd}' on {host}: {output}")
                    return False
                self.logger.info(f"Successfully executed '{cmd}' on {host}")

            return True

        except Exception as e:
            self.logger.error(f"Error setting up {host}: {str(e)}")
            return False
        finally:
            client.close()

    def create_inventory_file(self) -> bool:
        """Create Ansible inventory file"""
        inventory_data = {
            'all': {
                'children': {
                    'k8s_cluster': {
                        'children': {
                            'master': {
                                'hosts': {
                                    'k8s-master': {
                                        'ansible_host': self.master_ip
                                    }
                                }
                            },
                            'workers': {
                                'hosts': {
                                    f'k8s-worker{i+1}': {
                                        'ansible_host': ip
                                    } for i, ip in enumerate(self.worker_ips)
                                }
                            }
                        }
                    }
                },
                'vars': {
                    'ansible_user': self.ssh_user,
                    'ansible_ssh_private_key_file': self.ssh_key_path,
                    'ansible_become': 'yes'
                }
            }
        }

        try:
            with open('inventory.yml', 'w') as f:
                yaml.dump(inventory_data, f, default_flow_style=False)
            return True
        except Exception as e:
            self.logger.error(f"Failed to create inventory file: {str(e)}")
            return False

    def create_ansible_cfg(self) -> bool:
        """ansible.cfg 파일 생성"""
        config_content = f"""[defaults]
inventory = inventory.yml
host_key_checking = False
remote_user = {self.ssh_user}
private_key_file = ~/.ssh/id_rsa

[privilege_escalation]
become = True
become_method = sudo
become_user = root
become_ask_pass = False
ansible_become_password = {self.ssh_password if self.ssh_password else ''}
"""
        try:
            with open('ansible.cfg', 'w') as f:
                f.write(config_content)
            return True
        except Exception as e:
            self.logger.error(f"Failed to create ansible.cfg: {str(e)}")
            return False

    def distribute_ssh_key(self, host: str) -> bool:
        """SSH 키 배포"""
        try:
            if self.ssh_password:
                cmd = f"sshpass -p {self.ssh_password} ssh-copy-id -i {self.ssh_key_path}.pub -o StrictHostKeyChecking=no {self.ssh_user}@{host}"
                success, output = self.run_command(cmd, shell=True)
                if not success:
                    self.logger.error(f"Failed to copy SSH key to {host}: {output}")
                    return False
            return True
        except Exception as e:
            self.logger.error(f"Error distributing SSH key to {host}: {str(e)}")
            return False

    def verify_ansible(self) -> bool:
        """Ansible 설치 확인"""
        success, output = self.run_command("ansible --version")
        if not success:
            self.logger.error("Ansible is not properly installed")
            return False
        self.logger.info("Ansible installation verified successfully")
        return True

    def run(self) -> bool:
        """전체 설정 프로세스 실행"""
        try:
            # SSH 키 생성
            if not self.create_ssh_key():
                return False

            # 모든 노드에 SSH 키 배포
            all_hosts = [self.master_ip] + self.worker_ips
            for host in all_hosts:
                if not self.distribute_ssh_key(host):
                    return False

            # 병렬로 노드 설정
            with ThreadPoolExecutor(max_workers=len(all_hosts)) as executor:
                future_to_host = {executor.submit(self.setup_node, host): host for host in all_hosts}
                for future in as_completed(future_to_host):
                    host = future_to_host[future]
                    try:
                        if not future.result():
                            self.logger.error(f"Failed to setup node: {host}")
                            return False
                    except Exception as e:
                        self.logger.error(f"Exception occurred while setting up {host}: {str(e)}")
                        return False

            # Ansible 설정 파일 생성
            if not self.create_inventory_file() or not self.create_ansible_cfg():
                return False

            # 설치 확인
            if not self.verify_ansible():
                return False

            self.logger.info("Ansible setup completed successfully!")
            return True

        except Exception as e:
            self.logger.error(f"Setup failed: {str(e)}")
            return False
        
class AnsibleVerification:
    def __init__(self, inventory_path: str = 'inventory.yml'):
        self.inventory_path = inventory_path
        self.setup_logging()
    
    def setup_logging(self):
        """Configure logging"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('ansible_verification.log')
            ]
        )
        self.logger = logging.getLogger(__name__)

    def run_ansible_command(self, command: str) -> tuple:
        """Ansible 명령어 실행"""
        try:
            result = subprocess.run(
                command,
                shell=True,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return True, result.stdout
        except subprocess.CalledProcessError as e:
            return False, f"Error: {e.stderr}"

    def verify_ansible_installation(self) -> bool:
        """Verify Ansible installation status"""
        checks = [
            ("ansible --version", "Checking Ansible installation"),
            ("ansible-playbook --version", "Checking Ansible-playbook installation"),
            ("ansible-galaxy --version", "Checking Ansible-galaxy installation")
        ]
        
        for command, description in checks:
            self.logger.info(f"\n=== {description} ===")
            success, output = self.run_ansible_command(command)
            if not success:
                self.logger.error(f"{description} failed: {output}")
                return False
            self.logger.info(output.strip())
        
        return True

    def verify_inventory(self) -> bool:
        """Verify inventory file"""
        self.logger.info("\n=== Checking Inventory File ===")
        
        if not os.path.exists(self.inventory_path):
            self.logger.error(f"Inventory file not found: {self.inventory_path}")
            return False
        
        success, output = self.run_ansible_command(f"ansible-inventory --list -i {self.inventory_path}")
        if not success:
            self.logger.error(f"Inventory file verification failed: {output}")
            return False
            
        self.logger.info("Inventory file verification successful")
        return True

    def test_connectivity(self) -> bool:
        """Test connection to all hosts"""
        self.logger.info("\n=== Testing Host Connectivity ===")
        
        # Test all hosts using ping module
        success, output = self.run_ansible_command(f"ansible all -i {self.inventory_path} -m ping")
        if not success:
            self.logger.error(f"Host connectivity test failed: {output}")
            return False
            
        self.logger.info("All host connectivity tests successful")
        return True

    def verify_sudo_access(self) -> bool:
        """Verify sudo permissions"""
        self.logger.info("\n=== Verifying Sudo Permissions ===")
        
        command = 'ansible all -i %s -m shell -a "sudo -n true" -b' % self.inventory_path
        success, output = self.run_ansible_command(command)
        if not success:
            self.logger.error(f"Sudo permission verification failed: {output}")
            return False
            
        self.logger.info("Sudo permission verification successful")
        return True

    def verify_python(self) -> bool:
        """Python 설치 확인"""
        self.logger.info("\n=== Python 설치 확인 ===")
        
        command = f"ansible all -i {self.inventory_path} -m shell -a 'python3 --version'"
        success, output = self.run_ansible_command(command)
        if not success:
            self.logger.error(f"Python 설치 확인 실패: {output}")
            return False
            
        self.logger.info(output.strip())
        return True

    def run_verification(self) -> bool:
        """Run all verifications"""
        checks = [
            (self.verify_ansible_installation, "Ansible Installation Verification"),
            (self.verify_inventory, "Inventory Verification"),
            (self.test_connectivity, "Connectivity Test"),
            (self.verify_sudo_access, "Sudo Permission Verification"),
            (self.verify_python, "Python Installation Verification")
        ]
        
        all_passed = True
        for check_func, description in checks:
            self.logger.info(f"\nExecuting: {description}")
            if not check_func():
                self.logger.error(f"{description} failed")
                all_passed = False
            else:
                self.logger.info(f"{description} successful")
                
        return all_passed

def verify_setup():
    """Run installation verification"""
    verifier = AnsibleVerification()
    if verifier.run_verification():
        print("\n✅ Ansible installation and configuration is successful.")
    else:
        print("\n❌ There are issues with Ansible installation or configuration. Please check the logs.")

def main():
    parser = argparse.ArgumentParser(description='Setup Ansible on multiple nodes')
    parser.add_argument('--master', required=True, help='Master node IP address')
    parser.add_argument('--workers', required=True, nargs='+', help='Worker node IP addresses')
    parser.add_argument('--user', default='sure', help='SSH user')
    parser.add_argument('--password', help='SSH password (if not using key-based auth)')
    
    args = parser.parse_args()
    
    setup = AnsibleSetup(
        master_ip=args.master,
        worker_ips=args.workers,
        ssh_user=args.user,
        ssh_password=args.password
    )
    
    if not setup.run(): 
        sys.exit(1)

    verify_setup()

if __name__ == "__main__":
    main()
