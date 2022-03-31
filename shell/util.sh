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

### MAC OS
## trigger sidecar to ipad
function m_sidecar() {
  cat <<EOF > /tmp/m_sidecar.scpt
use AppleScript version "2.4" -- Yosemite (10.10) or later
use scripting additions

set deviceName to "Martin's iPad"

tell application "System Events"
  tell its application process "ControlCenter"
    -- Click the Control Center menu.
    click menu bar item "Control Center" of menu bar 1

    -- Give the window time to draw.
    delay 1

    -- Get all of the checkboxes in the Control Center menu.
    set ccCheckboxes to name of (every checkbox of window "Control Center")

    if ccCheckboxes contains "Connect to Sidecar" then
      -- If one of the checkboxes is named "Connect to Sidecar," click that checkbox.
      set sidecarToggle to checkbox "Connect to Sidecar" of window "Control Center"
      click sidecarToggle

      -- This opens a secondary window that contains the button to actually connect to Sidecar. Give the window time to draw.
      delay 1

      -- In masOS Monterey, the Sidecar device toggle (checkbox) is inside of a scroll area.
      -- Rather than assume that it's in scroll area 1, get all of the scroll areas, loop through them, and find the device toggle.
      set scrollAreas to (every scroll area of window "Control Center")
      set saCounter to 1
      set displayCheckboxes to ""

      repeat with sa in scrollAreas
        set displayCheckboxes to name of (every checkbox of sa)

        if displayCheckboxes contains deviceName then
          -- Device toggle found.
          exit repeat
        end if

        -- We didn't find the device toggle. Try the next scroll area.
        set saCounter to saCounter + 1
      end repeat

      if displayCheckboxes contains deviceName then
        -- If we found the a checkbox with the iPad's name, `saCounter` tells us which scroll area contains the Sidecar toggle.
        set deviceToggle to checkbox deviceName of scroll area saCounter of window "Control Center"

        -- Click the toggle to connect Sidecar.
        click deviceToggle

        -- Click the Control Center menu to close the secondary menu and return to the main menu.
        click menu bar item "Control Center" of menu bar 1

        -- Click the Control Center menu again to close the main menu.
        click menu bar item "Control Center" of menu bar 1
      else
        -- Sidecar is available, but no devices with deviceName were found.
        display dialog "The device " & deviceName & " can't be found. Please verify the name of your iPad and update the `deviceName` variable if necessary."
      end if
    else
      -- A checkbox named "Connect to Sidecar" wasn't found.
      set isConnected to false
      repeat with cb in ccCheckboxes
        -- Loop through the checkboxes and determine if Sidecar is already connected.
        if cb contains "Disconnect" then
          -- If one of the checkboxes has "Disconnect" in its name, Sidecar is already connected.
          -- Break out of the loop.
          set isConnected to true
          exit repeat
        end if
      end repeat

      if isConnected is equal to true then
        -- Click the checkbox to disconnect Sidecar.
        set sidecarToggle to ((checkbox 1 of window "Control Center") whose name contains "Disconnect")
        click sidecarToggle

        -- Click the Control Center menu again to close the main menu.
        click menu bar item "Control Center" of menu bar 1
      else
        -- Sidecar isn't connected, and no devices are available to connect to. Show an error message.
        display dialog "No Sidecar devices are in range."
      end if
    end if
  end tell
end tell
EOF
  
  osascript /tmp/m_sidecar.scpt
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
env = 'staging' if 'staging' in cluster else 'production'
cmd = f"lyftkube --cluster {cluster} -e {env} kubectl -- -n {proj}-{env} {' '.join(sys.argv[1:])}"
print(cmd)

EoF
       )
    echo $cmd
    eval $cmd
}
