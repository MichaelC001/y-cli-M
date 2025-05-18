from rich.live import Live
from rich.markdown import Markdown
import time

# Content chunks derived from your log file
markdown_chunks = [
    'In Python, a class is a blueprint',
    ' for creating objects. An object is an instance of a class. Classes encapsulate data (attributes) and functions (methods) that operate on that data.\n\nThink',
    " of a class as a cookie cutter. The cookie cutter itself isn't a cookie, but you can use it to make many cookies. Each cookie (object) will have",
    " the same shape (defined by the class) but can have different features (like different colored frosting, which would be an attribute).\n\nHere's a simple example:\n\n```python\nclass Dog:\n    # This is a special",
    " method called the constructor.\n    # It's called when you create a new object (a new Dog).\n    def __init__(self, name, breed):\n        self.name = name  # Attribute: name of the",
    ' dog\n        self.breed = breed # Attribute: breed of the dog\n        self.tricks = []   # Attribute: a list to store tricks the dog knows\n\n    # This is a method (a function inside a class)\n    def bark(self):\n        return f"{self.name}',
    ' says Woof!"\n\n    # Another method\n    def add_trick(self, trick_name):\n        self.tricks.append(trick_name)\n        return f"{self.name} learned a new trick: {trick_name}"\n\n# Now, let\'s create some Dog objects (',
    'instances of the Dog class)\nmy_dog = Dog("Buddy", "Golden Retriever")\nyour_dog = Dog("Lucy", "Poodle")\n\n# Accessing attributes\nprint(f"My dog\'s name is {my_dog.name} and it\'s a {my_dog.',
    'breed}.")\nprint(f"Your dog\'s name is {your_dog.name} and it\'s a {your_dog.breed}.")\n\n# Calling methods\nprint(my_dog.bark())\nprint(your_dog.bark())\n\nprint(my_dog.add_trick',
    '("sit"))\nprint(my_dog.add_trick("roll over"))\nprint(f"{my_dog.name} knows these tricks: {my_dog.tricks}")\n\nprint(your_dog.add_trick("fetch"))\nprint(f"{your_dog.name}',
    ' knows these tricks: {your_dog.tricks}")\n```\n\n**Explanation of the example:**\n\n1.  **`class Dog:`**: This line defines a new class named `Dog`.\n2.  **`__init__(self, name, breed)`**: This is the constructor method.\n    *',
    "   `self` is a reference to the current instance of the class (the specific dog being created). It's always the first parameter in instance methods.\n    *   `name` and `breed` are parameters that you pass when creating a `Dog` object.\n    *   Inside `__init__`,",
    " `self.name = name` and `self.breed = breed` create and initialize instance attributes. `self.tricks = []` initializes an empty list for each dog.\n3.  **`bark(self)`**: This is an instance method. It can access the instance's attributes (like `self.",
    'name`).\n4.  **`add_trick(self, trick_name)`**: Another instance method that modifies the `self.tricks` attribute.\n5.  **Creating Objects (Instances)**:\n    *   `my_dog = Dog("Buddy", "Golden Retriever")` creates an instance',
    ' of the `Dog` class. The `__init__` method is called automatically. `my_dog` now refers to this specific `Dog` object.\n    *   `your_dog = Dog("Lucy", "Poodle")` creates another distinct `Dog` object.\n6.  **Accessing',
    " Attributes**: You use dot notation (e.g., `my_dog.name`) to get the value of an object's attribute.\n7.  **Calling Methods**: You also use dot notation (e.g., `my_dog.bark()`) to call an object's method.\n\n",
    'In essence, classes help you organize your code by grouping related data and behavior into reusable and logical units.',
    '' # Final empty chunk from the log, kept for consistency with log data
]

full_markdown_content = ""
# Using default refresh_per_second for Live, which is 4.
# The first example used refresh_per_second=10, we can keep that for smoother updates.
with Live(refresh_per_second=10) as live:
    for chunk in markdown_chunks:
        full_markdown_content += chunk
        # Create a new Markdown object with the *entire* accumulated content each time
        markdown_to_display = Markdown(full_markdown_content)
        live.update(markdown_to_display)
        
        # Simulate the delay between receiving chunks
        # The original first script used 0.5s.
        # Your log timings were often around 0.4s-0.6s. 0.5s is a good average.
        if chunk: # Only sleep if the chunk added content
            time.sleep(0.5)

# After the 'with Live(...)' block finishes, the live display is typically cleared.
# If you want to see the final result persist, you'd print it here:
# from rich.console import Console
# console = Console()
# console.print("\n--- Streaming Complete (final output printed separately) ---")
# console.print(Markdown(full_markdown_content))

