sudo make 
sudo insmod cubic_z_score.ko
sudo /sbin/sysctl -w net.ipv4.tcp_congestion_control=cubic_z_score
