Test this end-to-end workflow in the dev environment unless otherwise specified by the user.

- Create a test skill with an extended definition of environment and evals that supports Bayesian hypothesis testing.

    - The skill should perform Bayesian A/B testing using PyMC.

      - Generate a dataset with two categories of log-normally distributed random variables, each with a different mean (20 samples per category).

      - Ensure the skill selects appropriate priors and specifies the correct probabilistic model.

      - Perform Bayesian hypothesis testing.

    - It should also define an evals Judge that verify:

      - The hypotheses of the model are correctly spelled out in the skill’s output.

     - Sampling converges successfully with no diagnostic issues.

    - And define an environment with PyMC 5.27.1. 
- upload that to the hub and run the evals
- check that the evals run and report on the output
