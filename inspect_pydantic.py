try:
    import inspect

    from pydantic_ai.models.openai import OpenAIModel

    print("OpenAIModel found")
    print(inspect.signature(OpenAIModel.__init__))
except Exception as e:
    print(e)
