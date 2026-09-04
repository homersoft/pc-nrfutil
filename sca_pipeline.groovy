@Library('JenkinsMain@2.34.0')_


pipelinePySCA(
    agentLabel: "pylint",
    pythonVersion: "3.14",
    baseBranch: "master",
    additionalAptPkgs: "pkg-config libdbus-1-dev libdbus-glib-1-dev libgirepository-2.0-dev",
    credentials: "1479b83d-f7b2-4823-8105-549616393cc5",
    install: {
        sh("pip install --upgrade pip")
        // requirements-frozen.txt first so the exact pins win the resolve over the
        // loose ranges pulled in transitively by requirements-dev.txt -> requirements.txt
        sh("pip install -r requirements-frozen.txt -r requirements-dev.txt")
        sh("pip install -e . --no-deps")
    },
    build: {
        sh("pip install --upgrade build")
        sh("python -m build --wheel")
    },
    checks: [
        DependencyCheck: {
            runScriptAndSetGitStatus("pip check", "Dependency Check")
        },
        Tests: {
            runScriptAndSetGitStatus("pytest", "Unit Tests")
        },
    ],
)
