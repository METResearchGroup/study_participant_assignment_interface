# V1 system design

## Problem statement

We have inconsistent and repeated logic across online experiments where we can't consistently assign participants to the assets that they should see in an experiment.

This is largely solved in platforms like Qualtrics, but it ties us to using these platforms. This is undesirable as we create a lot of websites to do our experiments.

We have three problems:

- We often create the assets that users will see (e.g., which posts they'll be shown) on-demand. This means we don't know what users will be shown until we create it on-demand. We would rather precompute these, check them for correctness/balance/quality first, and then as users log on, we assign them to one of the precomputed bundles. This can be slightly lossy if we care about edge cases (e.g., a participant is assigned but they drop out during the study), but given the low cost of creating these bundles, we overprovision them.
- We determine a participant's condition on-demand. Doing this means that we do balancing and assignment on-demand. This is not an atomic operation. Our existing solution has been that once a user logs in, we load a .json file of the users assigned to each condition. However, this leads to prominent TOCTOU race conditions: two users can log in at the same time, see an identical .json file, and both try to update it but upon updating, both their records override each other, so we only record the updated state of whoever was updated second. Given that our studies are decently long (>=5-10 minutes), the window for this TOCTOU race makes this a real concern. We want a solution that implements a something liike an atomic "compare-and-swap" operation (specifically for our caase, something like an atomic "read-then-update") so that users cannot be assigned to a bundle that someone else has already been assigned to.
- The above 2 problems are reimplemented over and over across experiments.

To solve this problem, we create a single unified design to manage the (1) precomputation of study assets and (2) atomic assignment of study users to a study condition (and thus picking which study assets will be given to them).

## Initial design

The initial design will have this high-level setup:

- S3 for blob storage.
- DynamoDB for atomic assignment.
- Lambdas for intermediate operations (e.g., running precomputation, accessing assignments from DynamoDB).
