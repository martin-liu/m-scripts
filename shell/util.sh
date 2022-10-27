## emacs
e(){
    visible_frames() {
        emacsclient -a "" -e '(length (visible-frame-list))'
    }

    change_focus() {
        emacsclient -n -e "(select-frame-set-input-focus (selected-frame))" > /dev/null
    }

    # try switching to the frame incase it is just minimized
    # will start a server if not running
    test "$(visible_frames)" -eq "1" && change_focus

    if [ "$(visible_frames)" -lt  "2" ]; then # need to create a frame
        # -c $@ with no args just opens the scratch buffer
        emacsclient -n -c "$@" && change_focus
    else # there is already a visible frame besides the daemon, so
        change_focus
        # -n $@ errors if there are no args
        test  "$#" -ne "0" && emacsclient -n "$@"
    fi
}

et(){
    exec emacsclient -a "" -t "$@"
}

function m_add_ssh_key() {
    cat ~/.ssh/id_rsa.pub | ssh $(m ssh g $1) 'cat >> /tmp/1.txt && mkdir -p .ssh && cat /tmp/1.txt >> .ssh/authorized_keys'
}

# Grant user access && sudo to a remote server
# Usage: `m_grant_user_sudo_access SERVER USER`
function m_grant_user_sudo_access() {
    server=$1
    usr=$2
    if [ -z "$server" ] || [ -z "$usr" ]
    then
        echo "no Server or User specific" && return
    fi
    command="
sudo sed -i 's|-:ALL:ALL|+:${usr}:ALL\n-:ALL:ALL|g' /etc/security/access.conf && \
echo '$usr ALL=(ALL) NOPASSWD:ALL' | sudo tee --append /etc/sudoers.d/ldapuser
"
    m ssh s $server $command
}

# ansible tora -a "key='SSH_PUB_KEY' user=root" -m authorized_key -u hualiu -s -k -K
function m_ansible_add_ssh_key() {
    group=$1
    usr=$2
    shift
    shift
    option=$@

    if [ -z "$group" ] || [ -z "$usr" ]
    then
        echo "no Ansible Group or User specific" && return
    fi

    command="key={{ lookup('file', '~/.ssh/id_rsa.pub') }} user=$usr"
    ansible $group -a "su $usr" -s $option
    ansible $group -a "$command" -m authorized_key -s $option
}

function m_ansible_grant_user_sudo_access() {
    group=$1
    usr=$2
    shift
    shift
    option=$@

    if [ -z "$group" ] || [ -z "$usr" ]
    then
        echo "no Ansible Group or User specific" && return
    fi
    command="
sudo sed -i 's|-:ALL:ALL|+:${usr}:ALL\n-:ALL:ALL|g' /etc/security/access.conf && \
echo '$usr ALL=(ALL) NOPASSWD:ALL' | sudo tee --append /etc/sudoers.d/ldapuser
"
    ansible $group -a "$command" -m shell -s $option
}

# ansible tora -m copy -a "src=docker-engine_1.12.5-0~ubuntu-trusty_amd64.deb dest=~"
# for Ubuntu 16
function m_ansible_install_docker() {
    group=$1
    shift
    option=$@
    ansible $group -a "wget 'https://apt.dockerproject.org/repo/pool/main/d/docker-engine/docker-engine_1.13.1-0~ubuntu-xenial_amd64.deb'" --sudo $option
    ansible $group -a "apt-get update && apt-get install -y libltdl7 && dpkg -i docker-engine_1.13.1-0~ubuntu-xenial_amd64.deb" --sudo $option
}


function m_ansible_setup_ssh() {

}

### MAC OS (ventra)
## trigger sidecar to ipad
function m_sidecar() {
osascript -e '
tell application "System Events"
    tell process "ControlCenter"
        click menu bar item 6 of menu bar 1
        delay 0.5
        click checkbox 1 of scroll area 1 of group 1 of window 1
    end tell
end tell';
}

### `lk describe pod core-prod-1/mlpsandbox-chatcanary-df6b8f765-xt6pk`
function lk() {
    cmd=$(python - $@ <<EoF

import sys
import os

i, pod_str = next((i, d) for i, d in enumerate(sys.argv) if '/' in d)
cluster, pod = pod_str.split('/')
sys.argv[i] = pod
proj = pod.split('-')[0]
if proj.startswith('realtime'):
    proj = proj[8:]
env = 'staging' if ('staging' in cluster or 'stg' in cluster) else 'production'
cmd = f"lyftkube --cluster {cluster} -e {env} kubectl -- -n {proj}-{env} {' '.join(sys.argv[1:])}"
print(cmd)

EoF
       )
    echo $cmd
    eval $cmd
}
