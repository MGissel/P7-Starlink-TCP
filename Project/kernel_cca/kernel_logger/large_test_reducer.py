import numpy as np 
from pathlib import Path

def reducer(test_name, max_time):
    data = np.loadtxt(f"{Path.home()}/P7-Starlink-TCP/Project/kernel_cca/{test_name}/test.log", delimiter=",", dtype=str)

    time = np.strings.strip(data[:,0], "[")
    time = np.strings.strip(time, "] ").astype(dtype=float)#data_matrix[0]
    time -= time[0]

    cutoff = np.searchsorted(time, max_time, side="left")

    np.savetxt(f"{Path.home()}/P7-Starlink-TCP/Project/kernel_cca/{test_name}/test_reduced.log", data[:cutoff], fmt="%s", delimiter=",")


test_name = "cubic_z_score_e"
max_time = 10 * 60 #Min -> sec 

reducer(test_name, max_time)