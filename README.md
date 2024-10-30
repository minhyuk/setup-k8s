# setup-k8s

쿠버네티스 클러스터를 자동으로 구성하기 위한 Ansible 기반 자동화 도구입니다.

## 개요

이 프로젝트는 다음과 같은 작업을 자동화합니다:

- Ansible 설치 및 구성
- Kubernetes 마스터 노드 설정
- Kubernetes 워커 노드 설정
- 컨테이너 런타임(Containerd) 설치
- Calico CNI 구성
- NVIDIA GPU 운영자 설치 (GPU가 있는 경우)

## 사전 요구사항

### VirtualBox 네트워크 구성

1. VirtualBox에서 각 VM에 대해 다음과 같이 네트워크를 구성합니다:

```
# /etc/systemd/network/20-wired.network 파일 생성
[Match]
Name=enp0s3

[Network]
Address=192.168.56.101/24  # 각 노드마다 다른 IP 할당
```

2. 네트워크 설정 적용:
```
sudo systemctl restart systemd-networkd
```

3. 네트워크 연결 확인:
```
ping 192.168.56.102  # 다른 노드로 ping 테스트
```

### SSH 키 설정

모든 노드에서 SSH 키 기반 인증이 가능하도록 설정해야 합니다:

```
ssh-keygen -t rsa -b 4096  # SSH 키 생성
ssh-copy-id sure@192.168.56.101  # 각 노드에 SSH 키 복사
```

## 설치 방법

1. 저장소 클론:
```
git clone https://github.com/your-username/setup-k8s.git
cd setup-k8s
```
2. 가상환경 설정:
```
python3 -m venv venv
source venv/bin/activate
```

3. 필요한 Python 패키지 설치:
```
pip install -r requirements.txt
```

4. Ansible 설치 실행:
```
python setup-ansible.py --master 192.168.56.101 --workers 192.168.56.102 192.168.56.103 192.168.56.104 --user sure --password suresoft
```
Sudo 패스워드가 필요한 패키지 설치를 위해 넣었음.


5. Ansible 설치 확인:
```
ansible --version
ansible-playbook --version
ansible-galaxy --version
```

6. 노드 연결 테스트:
```
ansible all -i inventory.yml -m ping -K
```

## Kubernetes 클러스터 구성

inventory.yml 은 ansible 설치가 끝나면 자동으로 현재디렉터리에 생성됨. 다만, k8s 설치를 하기 위해서 변경해야 하는데, 변경한 
inventory.yml 파일은 k8s 폴더에 넣어놨음! 참고바람


1. 마스터 노드 설정:
```
ansible-playbook -i inventory.yml k8s/master-setup.yml -K
```

2. 워커 노드 설정:
```
ansible-playbook -i inventory.yml k8s/worker-setup.yml -K
```

3. 클러스터 상태 확인:
```
kubectl get nodes
kubectl cluster-info
kubectl get pods --all-namespaces
```

## 문제 해결

### Kubelet 서비스 문제
Kubelet 서비스에 문제가 있는 경우:
```
sudo systemctl status kubelet
sudo journalctl -u kubelet  # 로그 확인
```

### 클러스터 초기화
문제가 발생한 경우 클러스터를 초기화하고 다시 시작:
```
sudo kubeadm reset -f
sudo rm -rf /etc/cni/net.d
sudo rm -rf $HOME/.kube/config
```

## 주의사항

- 모든 노드는 Ubuntu 24.04 LTS를 기반으로 합니다.
- 각 노드는 최소 2GB RAM과 2개의 CPU가 필요합니다.
- 마스터 노드는 최소 4GB RAM이 권장됩니다.
- 방화벽 설정에서 쿠버네티스 관련 포트가 열려있어야 합니다.

## 작성자

- Peter Kwon (minhyuk@suresofttech.com)

## 라이선스

이 프로젝트는 MIT 라이선스 하에 있습니다.
