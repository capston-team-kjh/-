import sys
import pickle
import numpy as np
from sklearn.naive_bayes import GaussianNB
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType

# 1. Tell Python to look in the parent folder for the custom module
sys.path.append('..')

model_filename = "state_classifier.pkl" 

print(f"Loading {model_filename}...")
with open(model_filename, "rb") as f:
    bundle = pickle.load(f)

# Extract the custom ML model
custom_model = bundle["model"]

print("Formatting dictionaries into 2D matrices...")
# 2. Extract the data from the custom dictionaries in the correct order
classes = custom_model.classes_

theta_matrix = []
var_matrix = []
prior_array = []

for c in classes:
    theta_matrix.append(custom_model.means_[c])
    var_matrix.append(custom_model.variances_[c])
    prior_array.append(custom_model.priors_[c])

print("Performing brain transplant to standard scikit-learn model...")
standard_model = GaussianNB()

# 3. Inject the clean, ordered matrices into the standard model
standard_model.classes_ = np.array(classes)
standard_model.class_prior_ = np.array(prior_array)
standard_model.theta_ = np.array(theta_matrix)
standard_model.var_ = np.array(var_matrix)

# 4. We know exactly how many features it needs now
num_features = 15
initial_type = [('float_input', FloatTensorType([None, num_features]))]

print("Converting to ONNX format...")
onnx_model = convert_sklearn(standard_model, initial_types=initial_type)

output_filename = "focus_classifier.onnx"
with open(output_filename, "wb") as f:
    f.write(onnx_model.SerializeToString())

print(f"Success! Saved as {output_filename}.")