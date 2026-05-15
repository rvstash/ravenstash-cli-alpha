# rvn-demo-java

Minimal Maven project for hands-on testing of `rvn` CLI commands.

## What's in here

| File | Purpose |
|------|---------|
| `pom.xml` | Real Maven project: jackson-databind, slf4j, commons-lang3, JUnit 5 |
| `src/main/.../Main.java` | CLI that hits the Maven Central search API |
| `src/main/.../Greeter.java` | Utility class (uses commons-lang3) |
| `src/test/.../GreeterTest.java` | JUnit 5 + AssertJ unit tests |

## Try it — public registry, no account needed

```bash
# 1. Install runtimes (once)
rvn system install java 21
rvn system install maven latest
source ~/.rvn/env           # or restart your shell

# 2. Pin runtime for the project (writes .java-version)
rvn java pin 21

# 3. Resolve and download all deps from Maven Central
rvn maven install           # mvn dependency:resolve

# 4. Inspect dependencies
rvn maven list              # mvn dependency:list
rvn maven tree              # mvn dependency:tree

# 5. Compile and run tests
mvn compile
mvn test

# 6. Build a fat JAR and run the demo
mvn package -DskipTests
java -jar target/rvn-demo-java-0.1.0.jar info com.fasterxml.jackson.core:jackson-databind
java -jar target/rvn-demo-java-0.1.0.jar versions org.slf4j:slf4j-api --limit 5
java -jar target/rvn-demo-java-0.1.0.jar versions org.apache.commons:commons-lang3

# 7. Check for version updates
mvn versions:display-dependency-updates
```

## Try it — private registry (needs rvn auth login)

```bash
# Login first
rvn auth login --api-url https://api.ravenstash.com

# Show the settings.xml snippet for your private Maven repo
rvn maven settings-xml --repo my-maven-repo

# Show the repository URL
rvn maven repo-url --repo my-maven-repo

# Deploy to your private Maven repo
rvn maven deploy --repo my-maven-repo

# Bump version (writes to pom.xml via mvn versions:set)
rvn maven bump patch          # 0.1.0 → 0.1.1
rvn maven bump minor          # 0.1.0 → 0.2.0

# Manage dist-tags (mapped to Maven metadata concepts)
rvn maven dist-tag ls  --repo my-maven-repo --name rvn-demo-java

# Snapshot publish (appends -SNAPSHOT automatically)
rvn maven snapshot publish --repo my-maven-repo
rvn maven snapshot ls     --repo my-maven-repo --name com.ravenstash.demo:rvn-demo-java

# Yank / deprecate a version
rvn maven yank       --repo my-maven-repo \
    --name com.ravenstash.demo:rvn-demo-java --version 0.1.0
rvn maven deprecate  --repo my-maven-repo \
    --name com.ravenstash.demo:rvn-demo-java --version 0.1.0 \
    --message "Use 0.1.1 instead"
```
