let messages = Array.from(document.querySelectorAll('[data-ui-test-id="message"]'));
let chatDump = messages.map(m => {
    let author = m.querySelector('[data-ui-id="message-author"]')?.innerText || "Unknown";
    let body = m.querySelector('[data-ui-id="message-body"]')?.innerText || "";
    return `[${author}]: ${body}`;
}).join('\n');
console.log(chatDump);
