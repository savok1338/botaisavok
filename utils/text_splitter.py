def split_text(text: str, max_chunk_size: int = 4000) -> list[str]:
    """
    Разбивает длинный текст на части, не превышающие max_chunk_size символов.
    
    Telegram имеет жесткий лимит 4096 символов на одно сообщение.
    Функция аккуратно делит текст по абзацам (\\n\\n), строкам (\\n) или пробелам,
    чтобы не разрывать слова и предложения посреди текста.
    """
    if not text:
        return []
    
    if len(text) <= max_chunk_size:
        return [text]
    
    chunks: list[str] = []
    current_chunk = ""
    
    # Сначала пробуем разбить по абзацам
    paragraphs = text.split("\n\n")
    
    for para in paragraphs:
        # Если добавление этого абзаца не превышает лимит
        candidate = f"{current_chunk}\n\n{para}" if current_chunk else para
        if len(candidate) <= max_chunk_size:
            current_chunk = candidate
        else:
            # Если текущий накопленный кусок уже есть, сохраняем его
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            
            # Если сам абзац больше max_chunk_size, делим его построчно
            if len(para) > max_chunk_size:
                lines = para.split("\n")
                for line in lines:
                    line_candidate = f"{current_chunk}\n{line}" if current_chunk else line
                    if len(line_candidate) <= max_chunk_size:
                        current_chunk = line_candidate
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                            current_chunk = ""
                        
                        # Если сама строка длиннее max_chunk_size, делим по словам
                        if len(line) > max_chunk_size:
                            words = line.split(" ")
                            for word in words:
                                word_candidate = f"{current_chunk} {word}" if current_chunk else word
                                if len(word_candidate) <= max_chunk_size:
                                    current_chunk = word_candidate
                                else:
                                    if current_chunk:
                                        chunks.append(current_chunk.strip())
                                        current_chunk = ""
                                    # Если даже отдельное слово длиннее лимита, режем жестко
                                    while len(word) > max_chunk_size:
                                        chunks.append(word[:max_chunk_size])
                                        word = word[max_chunk_size:]
                                    current_chunk = word
                        else:
                            current_chunk = line
            else:
                current_chunk = para
                
    if current_chunk and current_chunk.strip():
        chunks.append(current_chunk.strip())
        
    return chunks
