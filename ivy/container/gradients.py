# local
from ivy.container.base import ContainerBase

# ToDo: implement all methods here as public instance methods


# noinspection PyMissingConstructor
class ContainerWithGradients(ContainerBase):

    def __init__(self):
        import ivy.functional.ivy.gradients as gradients
        ContainerBase.add_instance_methods(self, gradients)
