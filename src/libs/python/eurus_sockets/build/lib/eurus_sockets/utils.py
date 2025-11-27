from .const import MESSAGES

class MessagesUtils:
    def __init__(self):
        pass
    def __compare_keys(self, msg, command):
        if msg.keys() == MESSAGES[command].keys():
            return True

        for key in msg.keys():
            if key not in MESSAGES[command].keys():
                raise KeyError(f"Ключа '{key}' не cуществует в сообщении '{command}'")
    
    def __compare_types(self, msg, command):
        for key in msg.keys():
            if not isinstance(msg[key], MESSAGES[command][key]):
                raise TypeError(f"Тип данных ключа '{key}' не соответствует требуемому типу данных")
        return True
    
    def __compare_data(self, msg, command):
        if command not in MESSAGES.keys():
            raise ValueError(f"Сообщение '{command}' не существует")
        for key in msg.keys():
            if msg[key] == abs(float("inf")):
                raise ValueError(f"Значение ключа '{key}' не может быть бесконечностью")
        return True
            
        
    def compare_messages(self, message):
        if not isinstance(message, dict):
            raise TypeError("Тип данных сообщения не является словарём")
        
        if "command" in message.keys():
            if self.__compare_data(message, message["command"]) and self.__compare_keys(message, message["command"]) and self.__compare_types(message, message["command"]):
                return True
        else:
            raise KeyError("В сообщении отсутствует ключ 'command'")
        return None

