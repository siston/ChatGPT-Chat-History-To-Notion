# ChatGPT Full Log To Notion

一个将你在 ChatGPT 的全部聊天记录导入 Notion 的简单脚本，让你的 Notion AI 继承 ChatGPT 记忆。

A simple script to import all your chat history in ChatGPT into Notion. Let your Notion AI inherit ChatGPT memory.

- [English](#English)
- [中文](#中文)

Scripts in different languages ​​differ only in the interface text, and the execution effects are the same.

### Introduction

This is a Python program, its goal is to import all the exported ChatGPT chat records into your Notion database. After that, you can easily use Notion AI to inherit a previous conversation.

You should not delete your ChatGPT account after using it, because some chat records may still be skipped due to formatting issues.

**Prerequisites:** Have a paid version of Notion, because the number of Blocks will be very large, which will inevitably exceed the limit of the free version of Notion;

### How to use

1. Go to "Settings" in the upper right corner of the ChatGPT interface, then select "Data Controls" and click Export.
3. Wait and receive an email from ChatGPT. Download the compressed package in the email to your local computer and decompress it. We will write it down and call it "Chat History Directory".
4. Download the import_chatgpt_en.py script from this project and place it in the "Chat History Directory".
5. Copy this template in Notion: https://www.notion.so/223ca795c956806f84b8da595d3647d6
6. Create a new integration in the [Notion Integration](https://www.notion.so/my-integrations) page, named ChatGPT Full Log To Notion
7. Find the database you just copied into your Workspace in Notion, and then add ChatGPT Full Log To Notion to the page in "Integration" in the upper right corner.
8. Use an editor to open the import_chatgpt_en.py you downloaded locally, follow the prompts to set NOTION_API_KEY (find it in your new integration, such as: ntn_54351xxxxxxxxxxxxxxxxd) and NOTION_DATABASE_ID (find it in the share button of Notion, such as: 223ca795c956806f84b8da595d3647d6), and then save.
9. Enter the terminal and first execute pip install requests tqdm to install dependencies;
10. Then enter the chat history directory and run the script: python import_chatgpt_en.py

It supports importing images and canvas, as well as most conversations, and supports breakpoint resuming. But in order to handle as many abnormal characters as possible, it is slow, and 1000 conversations take about 6 hours. Do not modify the target database before the complete import.

Use Ctrl+C to interrupt the import, and when it runs next time, it will continue from the unfinished part. If you need to start over, you need to delete the processed_ids.log file in the chat history directory.

## 中文

### 介绍

这是一个 Python 程序，它的目标是将已经导出的 ChatGPT 聊天记录全量导入你的 Notion 数据库中。在这之后，你可以轻易的使用 Notion AI 来继承曾经的某一个对话。

它支持导入图片和 Canvas，以及大部分的对话，支持断点续传。但为了尽可能多的处理异常字符，它的效率较慢，1000 个对话大约需要 6 小时。在完整导入之前，不要改动目标数据库。

你不应该在使用它后删除你的 ChatGPT 账号，因为仍有一些聊天记录可能会因为格式问题而被跳过。

**前提条件：**拥有付费版 Notion，因为 Blocks 数量会非常大，必然超过 Notion 免费版的限制；

### 使用方法

1. 在 ChatGPT 的界面右上角进入“设置”，然后选择“数据管理”，再点击导出。
3. 等待，并收到一封来自 ChatGPT 的邮件，将邮件中的压缩包下载到本地，并解压，我们记下来称之为“聊天记录目录”。
4. 从本项目下载 import_chatgpt.py 脚本，并放置在“聊天记录目录”。
5. 在 Notion 中复制这个模板： https://www.notion.so/223ca795c956806f84b8da595d3647d6
6. 在[Notion集成](https://www.notion.so/my-integrations)页面中创建一个新的集成，名字为 ChatGPT Full Log To Notion
7. 在 Notion 中找到你刚才复制进自己 Workspace 的那个数据库，然后在右上角的“集成”中，将 ChatGPT Full Log To Notion 添加到页面中。
8. 用编辑器打开你下载到本地的 import_chatgpt.py，按照其中的提示设置 NOTION_API_KEY（在你新建的集成中查找，形如：ntn_54351xxxxxxxxxxxxxxxxd）和 NOTION_DATABASE_ID（在 Notion 的分享按钮中查找，形如：223ca795c956806f84b8da595d3647d6），然后保存。
9. 进入终端，首先执行 pip install requests tqdm 安装依赖；
10. 然后进入到聊天记录目录，运行脚本：python import_chatgpt.py

它支持导入图片和 Canvas，以及大部分的对话，支持断点续传。但为了尽可能多的处理异常字符，它的效率较慢，1000 个对话大约需要 6 小时。在完整导入之前，不要改动目标数据库。

使用 Ctrl+C 可以中断导入，当下次运行时，它将从未完成的部分继续。如果你需要重头开始，需要删除聊天记录目录中的 processed_ids.log 文件。
