import numpy as np
#import pandas as pd 
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

# Written by Frederik B. B. Jepsen (and a little bit is written by IP)


# By IB
def process_time(time_col):
    #print(time_col[:10])
    time_col = np.strings.strip(time_col, "[")
    #print(time_col[:10])
    time_col = np.strings.strip(time_col, "] ").astype(dtype=float) 
    #print(time_col)
    return time_col





def plot_treshhold(t_n,z_n,treshold=3):

    colors = np.where(z_n >= treshold,"r","b")
    over = np.ma.masked_where(z_n > treshold,z_n)
    lower = np.ma.masked_where(z_n < treshold,z_n)

    plt.plot(t_n,z_n)
    plt.hlines(treshold,t_n[0],t_n[-1],colors="black",label=f"Treshhold {treshold}",linestyles="dashed")
    plt.grid()
    plt.legend()
    plt.show()



class treshold_analyzer:


    def __init__(self,time,z,rtt,max_tresh=100,debug = False):
        self.time = time
        self.z_score = z
        self.rtt = rtt

        if max_tresh == 0:
            self.max_tresh=z.max()
        else:
            self.max_tresh = max_tresh # maximum treshhold.



        self.treshold = 20
        self.debug = debug


    def _handover_counter(self,treshold : int):
        """
        This function is used to measure the duration of the handover and normal use.

        """
        over_treshhold = self.z_score >= treshold

        # Duratoins of states needs to be stored in a space at least at long as the amount of samples.
        starlink_handover = np.zeros((len(self.z_score),3))
        starlink_handover[:,-1] = -1 # not assigned


        # Counting the amount of times a state has changed (1 = handover, 0 = normal state)
        state_count= 0
        current_state = over_treshhold[0] # Which state do we start it

        index_state_time_begin = 0 # What time did the state start in

        # Find the duration of each state.
        for i in range(len(over_treshhold)):
            if over_treshhold[i] != current_state:

                # Beginning time of state.
                starlink_handover[state_count,0] = self.time[index_state_time_begin] 

                # End time of state
                starlink_handover[state_count,1] = self.time[i]

                # Current state.
                starlink_handover[state_count,2] = current_state

                # Update state and beginning index of the state
                current_state = over_treshhold[i]
                index_state_time_begin = i


                # Point to next index to save infomration about state duratoin.
                state_count +=1
        # CLEANUP
        # Remove the indexes that where not used (when a row in last collums has value -1)
        mask = np.where(starlink_handover[:,-1] != -1)
        starlink_handover = starlink_handover[mask]

       

        # TODO Make this part into a seperate method to plot it.
        if self.debug == True: # Frederik: I can use this later, so do not Delete this
            # Formats the handover duration variable, so it can be plotted here.
            test = np.zeros((starlink_handover.shape[0],starlink_handover.shape[1]+1))
            test[:,0] = starlink_handover[:,0]
            test[:,1] = starlink_handover[:,2]
            test[:,2] = starlink_handover[:,1]
            test[:,3] = starlink_handover[:,2]

            # Reshape so it can be plotted
            test = test.reshape(len(test)*2,2)
            # The times to plot for the state
            state_timestamp = test[:,0] # Timestamp
            state_state = test[:,1] # State
            plt.step(state_timestamp,state_state*treshold, label="Estimated Handover states.")
            plt.title(f"Handover state duration Z-score test for treshhold {treshold}")
            #plt.step(self.time,self.rtt,label = "rtt")


            z_score_coloring = np.where(over_treshhold == True,"red","black")
            # if step or plot is used, the results are misleading.
            plt.scatter(self.time,self.z_score,label = "z-score",color=z_score_coloring,marker ="|")
            
            plt.grid()
            plt.legend()
            plt.ylabel("State")
            #plt.yticks(y_axis,y_values)
            plt.xlabel("Time (seconds)")
            plt.show()


        return starlink_handover


        # 1 = handover
        # 0 = normal

    def maximiser(self,t_normal_state_min=14,t_normal_state_max=16):
        """
        To optimise the treshhold given minimum duration of normal state and max state.

        Count how many there are and save the treshhold value that gives the maximum.

        TODO Make it work after the changes in _handover_counter
        """

        # [treshhold, good_intervals]
        current_max = np.ones(2)*(-1) # This block is save the current maximum.


        for i in range(0,self.max_tresh):
            state_over_time = self._handover_counter(i)

            # Only look at duration of handover states.

            normal_state_mask = state_over_time[:,-1] == 0

            states = state_over_time[:,1]-state_over_time[:,0]

            normal_states = states[normal_state_mask]

            pass
            states_in_interval = normal_states[(t_normal_state_min <= normal_states) & (normal_states<= t_normal_state_max)]

            pass

            good_intervals = len(states_in_interval)

            if good_intervals > current_max[1]:
                current_max = [i,good_intervals]
            else:

                if good_intervals == current_max[1] and good_intervals != 0:
                    print(f" {i} with {good_intervals} is just as good as {current_max}?")

            #TODO Fancy logic to maximise for duration.

        print("[treshhold,good_normal_states]")
        print(current_max)






if __name__ == "__main__":
    np.set_printoptions(suppress=True) 

    # Load the log file (Only works for Ib's CUBIC Code printk statements)
    data = np.loadtxt("test.log", delimiter=",", dtype=str)



    #np.savetxt("rtt.log", data[:,2], fmt="%s")

    # Load ind data
    time = process_time(data[:,0])
    time -= time[0] # So times start at zero.

    rtt = data[:,2].astype(dtype=int)
    z = data[:,8].astype(dtype=int)
    cwnd = data[:,6].astype(dtype=int)
    srtt = data[:,40].astype(dtype=int)

    test = treshold_analyzer(time,z,rtt,100,debug=False)

    #test._handover_counter(21)
    test.maximiser(14,16)

