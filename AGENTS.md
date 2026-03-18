# Agent Instructions

This file provides instructions for AI agents working with this repository.

## Repository Overview

This is m-scripts, a personal CLI tools and shell scripts collection by Martin Liu.

### Project Structure

- `src/` - Rust source code for the `m` CLI tool
- `shell/` - Shell scripts for setup, aliases, and utilities
- `bin/` - Executable scripts (including `setup.sh`)
- `raycast/` - Raycast script commands

### Key Components

1. **Rust CLI (`m`)**: A command-line tool built with Rust and Clap
   - Main entry: `src/main.rs`
   - Lyftkube module: `src/lyftkube/` - kubectl wrapper commands

2. **Shell Scripts**: Setup and utility scripts for macOS development environment
   - `bin/setup.sh` - Initial environment setup
   - `shell/install.sh` - Tool installation
   - `shell/alias.sh` - Shell aliases
   - `shell/zsh.sh` - Zsh configuration

## Coding Standards

### General Rules

- The README.md file must explain the purpose of the repository
- The README.md file must be free of typos, grammar mistakes, and broken English
- The README.md file must be as short as possible and must not duplicate code documentation

### Rust Code

- Functions should have doc comments explaining their purpose
- Use meaningful variable names
- Error messages should be clear and concise
- Keep code simple and pragmatic for a personal tool

### Shell Scripts

- Use POSIX-compliant syntax where possible
- Prefer `#!/bin/bash` for complex scripts
- Include header comments explaining script purpose
- Use meaningful variable names
- Quote all variable expansions

## Testing

- Rust code may include inline tests in the same file (using `#[cfg(test)]`)
- Tests should verify basic functionality works correctly
- Keep tests simple and focused on one behavior at a time

## Change Guidelines

- Keep the existing code structure unless there is a strong reason to change it
- Minor inconsistencies and typos in existing code may be fixed
- New features should follow the existing patterns in the codebase
