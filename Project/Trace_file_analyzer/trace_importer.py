import numpy as np
#Written by Frederik B B Jepsen
from matplotlib import pyplot as plt
from numba import jit, prange

class TI:

    def __init__(self):
        self.KEEP = 0
        self.LATENCY = 1
        self.RATE = 2
        self.LOSS = 3
        self.LIMIT = 4


@jit(nopython=True)
def moving_average(data,windows_size):
    pass

    new_data = np.zeros(len(data))

    # why it is a moving average
    # https://stackoverflow.com/questions/13728392/moving-average-or-running-mean
    test = np.convolve(data,np.ones(windows_size)/windows_size,mode="same") # signal boundries still visible.

    return test


#@jit
def sliced_average(raw_trace_data,window_size):
    #TODO Take average over time.
    
    slices = len(raw_trace_data)//window_size
    
    new_data = np.zeros((slices,raw_trace_data.shape[1]))
    
    new_data[:,0] = raw_trace_data[0,0]*window_size/10**6 # Convert to seconds
    new_data[:,0] = new_data[:,0].cumsum()
    
    for i in range(0,slices):
        pass
        new_data[i,1:] = np.sum(raw_trace_data[i*window_size:(i+1)*window_size,1:],axis=0)/window_size

    # Convert loss to percentage
    new_data[:,3]= new_data[:,3]/(2**32-1)*100

    # Convert latency to ms
    new_data[:,1] = new_data[:,1]/10**6
    
    print("Done")
    return new_data
    


def import_tracefile(file,window_size = 100,moving = True):
    """
    windows size of 100 = window is of length of a second)
    Keep = 0
    Latency = 1
    Rate = 2
    Loss = 3
    Limit = 4
    """



    #trace_simple_format = np.dtype([("Keep",np.uint64),("Latency",np.uint64),("Rate",np.int64),("Loss",np.uint32),("Limit",np.uint32)])
    raw_trace_data = np.loadtxt(file,delimiter=",")#,dtype=trace_simple_format)
    
    if moving == True:
    
        # convert loss to percentages.
        raw_trace_data[:,3] = (raw_trace_data[:,3]/(2**32-1))*100

        # Format latency to ms
        raw_trace_data[:,1] = raw_trace_data[:,1]/10**6

        # implement moving average
        raw_trace_data[:,1] = moving_average(raw_trace_data[:,1],window_size)
        raw_trace_data[:,3] = moving_average(raw_trace_data[:,3],window_size)
        # Format the data to seconds
        raw_trace_data[:,0] = raw_trace_data[:,0].cumsum()/10**6


        return raw_trace_data
    else:
        
        return sliced_average(raw_trace_data,window_size)


def plot_moving_mean(file,data,window_size,moving=True,normalize=False):

    trace_data = import_tracefile(file,window_size,moving)

    Axis_Labels = np.array(["Time (s)","Latency (ms)","Rate (bits/s)","Loss (%)","Limit (Queue Size)"])
    Desc_Labels = np.array(["Time","Latency","Rate","Packet loss Propability","Limit"])


    plt.xlabel(Axis_Labels[0])
    plt.ylabel(Axis_Labels[data])


    if normalize == False:
        plt.plot(trace_data[:,TI().KEEP],trace_data[:,data],label=Desc_Labels[data])
    else:
        for i in data:

            if i == TI().LOSS:

                plt.plot(trace_data[:,TI().KEEP],1-trace_data[:,i]/trace_data[:,i].max(),label="Packet success Prop")
            else:
                 plt.plot(trace_data[:,TI().KEEP],trace_data[:,i]/trace_data[:,i].max(),label=Desc_Labels[i])


    plt.legend()

    if moving == True:
        plt.title(f"""Sliding average of window size {window_size} ({window_size/100} s)\n 
        Over {trace_data[-1,0]/3600:.2f} Hours
        Normalized = {normalize}
            
        """)
    else:
        plt.title(f"""Compressed average over {window_size} ({window_size/100} s)\n 
            Over {trace_data[-1,0]/3600:.2f} Hours
            Normalized = {normalize}
            """)

    #TODO find a way to specify a slice.
    plt.grid()
    plt.show()

    


if __name__ == "__main__":
    file = "Project/TheaterQ_Traces/20260319_mixed_losssampling_eval_dl50.trace"
    new_file = "Project/TheaterQ_Traces/20260716_losssampling_eval.trace"
    dummy_file = "Project/Trace_file_analyzer/dummy.trace"

    #import_tracefile(new_file,moving=False)


    plot_moving_mean(new_file,[TI().LOSS,TI().RATE],50,False,True)



    pass