"""
# ###################################
# Group ID : <gr oup_id >
# Members : Frederik, Mathias, Ib and 
# Date : 9/9/2026
# Lecture: 1 Introduction to Machine Learning
# Dependencies: Numpy
# Python version: 3.14.3
# Functionality: Short Description. Example: This script trains a MLP for classifying
# handwritten digits. It also test the performance on a given data set for various
# settings.
# ###################################
"""

"""
Implement polynomial curve fitting for the data provided in 'ex01_data.npy' using the mean squared error (MSE) loss function. 
Additionally, experimentally investigate the impact of polynomial degree, regularization, and the number of data points on the performance and behaviour of the fitted polynomials.

"""

"""
1. Experiment with different polynomial degrees. Randomly select 10 data points from the data set using 'np.random.seed(100)'. 
Fit polynomial curves of degrees 0, 1, 2, 3, 4, and 9. Plot the resulting curves and report the corresponding errors. 
Using 'x1' as the independent variable (x) and 'x2' as the dependent variable (y). 


When increasing the number of degrees over 3, it becomes clear that while the MSE becomes lower, its MSE to the actual y value increases. 
"""

"""
2. Explore L2 regularization for a polynomial of degree 9 by choosing regularization parameters of 10, 1, 0.1 and 0.01. 
Plot the curves and report the errors.

With the increase of the regularization it attenuates the peaks of the polynomiums, this can help reduce overfitting and high degree regressions.
The higher the regularization is the more attenuation. The more extreme the polynomium peak is the more it is attenuated. 
Thus for the extreme case with 9 degrees, regularization = 10 helps the most. 
"""


"""
3. Investigate the effect of sample size. Now randomly select 100 data points from the data set using 'np.random.seed(100)'. 
Fit a polynomial of degree 9. Plot the curve and report the error.

When increasing the sample size it shows that the standard regression becomes very close to the l2 regression, which shows it is very important to have a lot of data to train on. 
Though l2 regularization still shows minor improvements at 10. 
"""



import numpy as np 
import matplotlib.pyplot as plt
from sklearn.linear_model import Ridge 
dataset = np.load("ex01_240903/ex01_data.npy") 

x1 = dataset[:,0] #
x2 = dataset[:,1] 
y = dataset[:,2] 

sample_size = 10
nr_of_degrees = np.array([0, 1, 2, 3, 4, 9])
nrows = 2
np.random.seed(seed=100)


degree_count = len(nr_of_degrees)
ncols = (degree_count//nrows)+degree_count%nrows
dataset_size = np.shape(x1)[0]
dataset_min = np.min(x1)
dataset_max = np.max(x1)


random_indices = np.random.choice(dataset_size, sample_size, replace=False)
sample_x1, sample_x2 = x1[random_indices], x2[random_indices]


for regularization in [10]: #1, 0.1, 0.01
    fig, ax = plt.subplots(nrows=nrows, ncols=ncols, figsize=(15, 12))
    for count, deg in enumerate(nr_of_degrees):
        polynomial = np.polynomial.polynomial.Polynomial.fit(sample_x1, sample_x2, deg=deg) #Returns the function 

        X = np.vander(sample_x1, N=deg+1, increasing=True)
        ridgepol = Ridge(alpha=regularization)
        ridgepol.fit(X, sample_x2)
        

        #Convert to data points 
        polynomial_x, polynomial_y = polynomial.linspace(n = dataset_size, domain=[dataset_min, dataset_max])
        l2_polynomial = ridgepol.predict(np.vander(x1, N=deg+1, increasing=True))

        MSE = 1/sample_size*(np.sum((polynomial_y[random_indices]-sample_x2)**2))
        RMSE = 1/sample_size*(np.sum((polynomial_y[random_indices]-y[random_indices])**2))
        WMSE = 1/dataset_size*(np.sum((polynomial_y-y)**2))

        LMSE = 1/sample_size*(np.sum((l2_polynomial[random_indices]-sample_x2)**2))
        LRMSE = 1/sample_size*(np.sum((l2_polynomial[random_indices]-y[random_indices])**2))
        LWMSE = 1/dataset_size*(np.sum((l2_polynomial-y)**2))

        ax[count//ncols, count%ncols].plot(x1, y, label="Real data", c="black")
        ax[count//ncols, count%ncols].scatter(sample_x1, sample_x2, c='blue')
        #ax[count//ncols, count%ncols].plot(x1, polynomial_y, label="Regression", c="red")
        ax[count//ncols, count%ncols].plot(x1, l2_polynomial, label="l2 Regression", c="green", linestyle="-.")

        
        ax[count//ncols, count%ncols].set_title(f'Degree Nr: {deg}\n MSE: {(MSE):.2f}, RMSE {(RMSE):.2f}, WMSE {WMSE:.2f}\nLMSE: {(LMSE):.2f}, LRMSE {(LRMSE):.2f}, LWMSE {LWMSE:.2f}')
        
    plt.legend()
    plt.tight_layout()
    #plt.savefig(f"ex01_240903/Sample_{sample_size}_regularization_{regularization}.pdf", dpi=1000)
    plt.show()