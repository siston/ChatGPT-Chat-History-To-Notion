# ChatGPT Chat History Importer to Notion 📚✨

![GitHub Release](https://img.shields.io/github/release/siston/ChatGPT-Chat-History-To-Notion.svg) ![GitHub Issues](https://img.shields.io/github/issues/siston/ChatGPT-Chat-History-To-Notion.svg) ![GitHub Stars](https://img.shields.io/github/stars/siston/ChatGPT-Chat-History-To-Notion.svg)

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Supported Platforms](#supported-platforms)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

---

## Overview

ChatGPT-Chat-History-To-Notion is a straightforward script designed to help you import all your ChatGPT conversations directly into Notion. This tool allows you to keep your chat history organized and easily accessible. 

You can download the latest version of the script from the [Releases section](https://github.com/siston/ChatGPT-Chat-History-To-Notion/releases). Once downloaded, follow the instructions to execute the script.

---

## Features

- **Easy Import**: Quickly transfer your ChatGPT chat history to Notion.
- **User-Friendly**: Simple setup process with clear instructions.
- **Organized Storage**: Keep your chats organized in Notion for easy access.
- **Open Source**: Contribute to the project or customize it to your needs.

---

## Installation

To install the script, follow these steps:

1. **Download the Script**: Visit the [Releases section](https://github.com/siston/ChatGPT-Chat-History-To-Notion/releases) and download the latest version of the script.

2. **Extract Files**: If the downloaded file is compressed, extract it to a folder on your computer.

3. **Dependencies**: Make sure you have Python installed. You can download it from [python.org](https://www.python.org/downloads/).

4. **Install Required Packages**: Open your terminal or command prompt and navigate to the folder where you extracted the script. Run the following command to install the necessary packages:

   ```bash
   pip install -r requirements.txt
   ```

---

## Usage

After installation, you can run the script to import your chat history.

1. **Open Terminal**: Navigate to the folder containing the script.

2. **Run the Script**: Execute the script using the following command:

   ```bash
   python import_chat_history.py
   ```

3. **Follow Prompts**: The script will guide you through the process. You will need to provide your Notion API token and select the ChatGPT chat files you wish to import.

4. **Check Notion**: Once the import is complete, open Notion to see your chat history organized in the specified database.

---

## Configuration

You may need to configure a few settings before running the script. Here’s how:

- **Notion API Token**: You must create an integration in Notion and get an API token. Follow the instructions on the [Notion API documentation](https://developers.notion.com/docs/getting-started) to set this up.

- **Database ID**: You will also need the ID of the Notion database where you want to store your chats. You can find this in the URL of your database.

- **Script Settings**: Open the `config.py` file to adjust any other settings as needed, such as the default database ID or output format.

---

## Supported Platforms

This script works on:

- Windows
- macOS
- Linux

Ensure you have Python installed on your system for compatibility.

---

## Contributing

We welcome contributions to enhance this project. If you would like to contribute, please follow these steps:

1. **Fork the Repository**: Click the "Fork" button at the top right of this page.
2. **Create a Branch**: Use the following command to create a new branch:

   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make Changes**: Implement your changes and commit them:

   ```bash
   git commit -m "Add your message here"
   ```

4. **Push Changes**: Push your changes to your forked repository:

   ```bash
   git push origin feature/your-feature-name
   ```

5. **Open a Pull Request**: Navigate to the original repository and click on "New Pull Request".

For detailed guidelines, please refer to the [CONTRIBUTING.md](CONTRIBUTING.md) file in this repository.

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details.

---

## Contact

For any questions or suggestions, feel free to reach out:

- **Email**: your-email@example.com
- **GitHub**: [siston](https://github.com/siston)

You can also check the [Releases section](https://github.com/siston/ChatGPT-Chat-History-To-Notion/releases) for updates and new features.