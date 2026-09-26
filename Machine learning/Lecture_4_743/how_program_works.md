Just a quick guide on how the program work for M4

We got a 94.57% accuracy for classification of the test data after training the model


# Loading data
This part was done by the hints.
The data was normalized so every dimensions max value is 1.


# The actualt assignment

Here is what we actually did.

## Dimension reduction.

First make a LDA object, here the amount of dimensions to reduce to is specified. However as we have 3 classes, the  `n_components` variable defaults to $C_{count} - 1$ which is in the dataset $2$.

`analyse = LDA(n_components=2) # No need to modify`

Then the fit_transform method both fits the LDA to the training data, so other data can be transformed based on the training data. It also at once transform the training data, so we can plot and see the results.

 `analyse.fit_transform(train_data,train_targets)`

## The tools.py classes

In a semi-failed attempt to make the programming simpler, two classes where defined in *tools.py*. In practice these classes works as dictionaries with convenient methods.

The `trainset_class` which is used to calculate and store the mean and covariance of the each class in the training data. The prior has to be inserted manually either based on the sample size of all training data or manually defined as a propability of occurence. Futhermore there is a `pdf` method that calculates the bivariante Gaussian distribution of a datapoint belonging to a specific classification, where the mean, covariance and prior is automatically called by the class.


    if self.prior == None:
        self.prior("Note prior not set")

        res = nvm.pdf(test_data,mean=self.mean,cov=self.cov)
    else:
        res = nvm.pdf(test_data,mean=self.mean,cov=self.cov)*self.prior



`test_set_classificaion` Simply stores the class label for each datapoint along with the class label the trained algorithm aqquires.


## Classifying the test data

Before the training data is classified they are transformed by the object, which the training data trained to reduce the test data into two dimensions.

While the `Classify` method uses MLE to estimate which class a data point is most likely to belong to, **It currently does not handle edge cases with any method**.

the `p_list` variable is a propability matrix where each row represents data point $x_i$'s propability of belonging to a class $C_j$. So matrix index [$i$,$j$] means $p(x_i,C_j)$ Then for each row the highest propability is found and then the data point $i$ is classified as class $C_j$


In the end the accuracy of the label assignment is calculated and then the accuracy of the label assignment is calculated as a percentage.

**The program is not done**