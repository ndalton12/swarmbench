# ~/.bashrc
[ -z "$PS1" ] && return
HISTSIZE=5000
HISTFILESIZE=10000
shopt -s histappend checkwinsize
PS1='\u@\h:\w\$ '
alias ll='ls -alF'
alias la='ls -A'
