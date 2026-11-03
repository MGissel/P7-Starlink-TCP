name="${PWD##*/}"

sudo make NAME=$name
sudo insmod $name.ko
make NAME=$name clean
sudo /sbin/sysctl -w net.ipv4.tcp_congestion_control=$name
