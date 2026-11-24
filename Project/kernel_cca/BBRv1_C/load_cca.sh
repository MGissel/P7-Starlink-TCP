name="${PWD##*/}"
sudo rmmod $name.ko -f
sudo make NAME=$name
sudo insmod $name.ko
make NAME=$name clean
sudo sysctl -w net.ipv4.tcp_allowed_congestion_control="reno bbr cubic $name"
sudo ip link set dev lo mtu 1500
#65536 remember to change it back at some point