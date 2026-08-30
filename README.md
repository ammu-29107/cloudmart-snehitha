# cloudmart-snehitha
## Milestone 1:
Goal: Get the GitHub repository up and the high-level design documented on day one. This is a lightweight kickoff checkpoint — detailed design work continues into Milestone 2.
1. There are a lot of things that need alterations, but a baisc architecture has been created to make sure that the flow is clear.
2. Mentors have suggested many changes, along with my interviewer (Ravi Sangubotla). Hence, the updated architecture is yet to be drafted, and a clear one will be posted after completing Milestone 4, so that there could be a clarity regarding what services are being used, and what is the flow.

## Milestone 2:
Goal: Complete, detailed system design signed off and core infrastructure deployed via the CI/CD pipeline. No business logic yet — the pipeline and network foundation must be working before any application code is written.
1. A documentation was submitted, which has furhter mistakes and that required further understanding regarding the services that are being used.
2. There has been a lot of changes compared to Milestone 1 and Milestone 2 that mainly focused on RDS vs DynamoDB, and usage of Entity-Relationship between many other tables that have to be used in this project.
3. The network-stack also required changes such as using Multi-AZ for RDS which required a subnet group consisting of two private subnets.
4. Also, a clear permissions have been drafted to make sure that the services follow least-privilege permissions, which also needed corrections due to putting insufficient permissions.
5. There was a mistake that involves using authorization, which was included in the product-stack, that created product-stack requiring functions, IAM roles along with authroization requiring services.