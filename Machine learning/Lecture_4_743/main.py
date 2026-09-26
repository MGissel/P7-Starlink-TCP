# Frederik's sollution
# %%
import numpy as np
import tools
from scipy.stats import multivariate_normal as norm
import matplotlib.pyplot as plt
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis as LDA

# %% [markdown]
# # Loading the training and test data

# %% [markdown]
# ## Train data

# %%
train5 = np.loadtxt("mnist_all/train5.txt") / 255  # /255 for normalization
train6 = np.loadtxt("mnist_all/train6.txt") / 255
train8 = np.loadtxt("mnist_all/train8.txt") / 255

# %%
# Define targets
train5_target = 5 * np.ones(len(train5))
train6_target = 6 * np.ones(len(train6))
train8_target = 8 * np.ones(len(train8))

# %%
# Combine data
train_data = np.concatenate([train5, train6, train8])
train_targets = np.concatenate([train5_target, train6_target, train8_target])

# %% [markdown]
# ## Test data

# %%
test5 = np.loadtxt("mnist_all/test5.txt") / 255
test6 = np.loadtxt("mnist_all/test6.txt") / 255
test8 = np.loadtxt("mnist_all/test8.txt") / 255

# Define targets
test5_target = 5 * np.ones(len(test5))
test6_target = 6 * np.ones(len(test6))
test8_target = 8 * np.ones(len(test8))

# Combine
test_data = np.concatenate([test5, test6, test8])
test_targets = np.concatenate([test5_target, test6_target, test8_target])

# Class names
classes = np.array([5, 6, 8])



# %% [markdown]
# # Part 1: Reduce dimension to 2
# Here, we wish to reduce the data dimensionality from 784 to 2 using Linear Disicriminant Analysis (LDA).
# For this you can use scikit-learn. The LDA class in scikit-learn fits a covariance matrix and compute eigenvectors for you. LDA assume that you know about the classes, so you have to use the concatenated training set and targets/classes.

# %%
# Fit a scikit learn LDA instance to training data

analyse = LDA(n_components=2) # No need to modify
analyse.fit_transform(train_data,train_targets)
# %%
# Transform train data from each class using fitted LDA instance

tr_train_data = analyse.transform(train_data)

# The class calculates mean
tr_train5 = tools.trainset_class(tr_train_data[train_targets == 5],train5_target,"transformed class 5")
tr_train6 = tools.trainset_class(tr_train_data[train_targets == 6],train6_target,"transformed class 6")
tr_train8 = tools.trainset_class(tr_train_data[train_targets == 8],train8_target,"transformed class 8")



plt.scatter(tr_train5.data[:,0],tr_train5.data[:,1], label = "Class 5")
plt.scatter(tr_train6.data[:,0],tr_train6.data[:,1], label = "Class 6")
plt.scatter(tr_train8.data[:,0],tr_train8.data[:,1], label = "Class 8")
plt.legend()
plt.grid()
plt.show()

# %% [markdown]
# # Part 2: Perform 3-class classification based on the generated 2-dimensional data.
# We need to find a model to classify the test data as either 5, 6, or 8.
# Here, we could use a Gaussian model for each class, and estimate the mean and covariance from the dimensionality reduced data.


""" Make The mean, cov and priors"""
sample_size = len(tr_train5.data)+len(tr_train6.data)+len(tr_train8.data)

tr_train5.set_prior(sample_size=sample_size)
tr_train6.set_prior(sample_size=sample_size)
tr_train8.set_prior(sample_size=sample_size)




# %% [markdown]
# ## Estimate Gaussians using 2-dimensional data obtained from LDA



""" Done via "tools.dataset_class.pdf()" """
# Combine
test_data = np.concatenate([test5, test6, test8])
test_targets = np.concatenate([test5_target, test6_target, test8_target])


tr_test_data = analyse.transform(test_data)


# Do not use their pdf.
#tr_test5 = tools.test_set_classificaion(tr_test_data[test_targets == 5],test5_target,"test data class 5")
#tr_test6 = tools.test_set_classificaion(tr_test_data[test_targets == 6],test6_target,"test data class 6")
#tr_test8 = tools.test_set_classificaion(tr_test_data[test_targets == 8],test8_target,"test data class 8")

tr_test_data = tools.test_set_classificaion(tr_test_data,test_targets,"Test data")

def classify(classes_label_list,test_data : tools.test_set_classificaion):
    """

    Estimates the accuracy of the model based on training data.

    Does not take edge cases where the highest propability is of two different data types.

    """

    c_list = [c.label[0] for c in classes_label_list]

    # numpy of shape (data_points,classes)
    p_list = np.zeros(shape=(len(test_data.label),len(c_list)))

    for i in range(0,len(c_list)):

        # estemate the propability of each point in dataset belonging to distribtution.
        p_of_x = classes_label_list[i].pdf(test_data.data)

        # Saves the propability of each data point.
        p_list[:,i] = p_of_x.T
        

    # np.max(p_list) over axis = 1 must be done

    for i in range(len(p_list)):

        class_index =np.where(p_list[i] ==  np.max(p_list[i]))
        class_index = class_index[0][0]

        test_data.class_guess[i] = c_list[class_index]

        pass

    # Count the number of correct predictions
    no_correct = np.count_nonzero(test_data.class_guess==test_data.label)

    # the percentage of correct quesses
    accuracy = no_correct/(len(test_data.data))

    print(f"accurary for exercise a) = {accuracy}")


classify([tr_train5,tr_train6,tr_train8],tr_test_data)



pass

# %%
# Estimate parameters for a bivariante Gaussian distribution.




# %% [markdown]
# ## Classifying test data
# To classify the test data, we first transform it to 2-dimensions as well.





# %%
# Transform test data using fitted LDA instance

# %% [markdown]
# Now we compute priors, likelihoods and posteriors

# %%
# Compute priors
# Compute Likelihoods
# Compute posteriors

# %% [markdown]
# We can now compute the classification accuracy for the LDA-dimensionality reduced data

# %%
# Compute predictions

# Compute accuracy

# %% [markdown]
# What does the results show?

# %% [markdown]
# # (Optional Task) Comparison with PCA

# %% [markdown]
# This (optional!) task involves reducing the dimensionality of the data instead using PCA in order to compare it with LDA.

# %%
from sklearn.decomposition import PCA

# %% [markdown]
# ## Part 1

# %% [markdown]
# Optionally also fit The PCA class in scikit-learn fits a covariance matrix and compute eigenvectors for you.
# PCA doesn't assume any knowledge about the classes, so you have to use the concatenated training set.

# %%
# Fit a scikit learn PCA instance to training data

# %% [markdown]
# Now that the PCA model is fit to the training data, we can find a low dimesional representation of each class.

# %% [markdown]
# Let's try to plot the dimensionality reduced data and compare PCA to LDA. What do we see?

# %%
# Scatter plot of the dimensional-reduced data

# %%
# Transform train data from each class using fitted PCA instance

# %% [markdown]
# In the above plot we should see that LDA is seemingly better at seperating the tree classes,while the classes 5 and 8 are highly overlapped when using PCA.

# %% [markdown]
# ## Estimate Gaussians using 2-dimensional data obtained from PCA

# %%
# Estimate parameters for a bivariante Gaussian distribution.

# %% [markdown]
# ## Classifying test data
# To classify the test data, we first transform it to 2-dimensions as well.

# %%
# Transform test data using fitted PCA/LDA instance

# %% [markdown]
# Now we compute priors, likelihoods and posteriors

# %%
# Compute priors
# Compute Likelihoods
# Compute posteriors

# %%
# Compute predictions

# Compute accuracy

# %% [markdown]
# We can now compare the classification accuracy from PCA and LDA. What does the results show?

