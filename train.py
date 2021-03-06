#================================================================
#
#   File name   : train.py
#   Author      : PyLessons
#   Created date: 2020-05-05
#   Website     : https://pylessons.com/
#   GitHub      : https://github.com/pythonlessons/TensorFlow-2.x-YOLOv3
#   Description : used to train custom object detector
#
#================================================================
import os
os.environ['CUDA_VISIBLE_DEVICES'] = '0'
import shutil
import numpy as np
import tensorflow as tf
#from tensorflow.keras.utils import plot_model
#from tqdm import tqdm
from yolov3.dataset import Dataset
from yolov3.yolov3 import Create_Yolov3, YOLOv3, decode, compute_loss
from yolov3.utils import load_yolo_weights
from yolov3.configs import *

input_size = YOLO_INPUT_SIZE
logdir = TRAIN_LOGDIR
Darknet_weights = YOLO_DARKNET_WEIGHTS

save_best_only = True # saves only best agent according validation loss
save_checkpoints = False # saves all best validates checkpoints in training process (may require a lot disk space)

if os.path.exists(logdir): shutil.rmtree(logdir)
writer = tf.summary.create_file_writer(logdir)

trainset = Dataset('train')
testset = Dataset('test')
steps_per_epoch = len(trainset)
global_steps = tf.Variable(1, trainable=False, dtype=tf.int64)
warmup_steps = TRAIN_WARMUP_EPOCHS * steps_per_epoch
total_steps = TRAIN_EPOCHS * steps_per_epoch

if TRAIN_TRANSFER:
    Darknet = Create_Yolov3(input_size=input_size)
    load_yolo_weights(Darknet, Darknet_weights) # use darknet weights

yolo = Create_Yolov3(input_size=input_size, training=True, CLASSES=TRAIN_CLASSES)

if TRAIN_TRANSFER:
    for i, l in enumerate(Darknet.layers):
        layer_weights = l.get_weights()
        if layer_weights != []:
            try:
                yolo.layers[i].set_weights(layer_weights)
            except:
                print("skipping", yolo.layers[i].name)

optimizer = tf.keras.optimizers.Adam()


def train_step(image_data, target):
    with tf.GradientTape() as tape:
        pred_result = yolo(image_data, training=True)
        giou_loss=conf_loss=prob_loss=0

        # optimizing process
        for i in range(3):
            conv, pred = pred_result[i*2], pred_result[i*2+1]
            loss_items = compute_loss(pred, conv, *target[i], i, CLASSES=TRAIN_CLASSES)
            giou_loss += loss_items[0]
            conf_loss += loss_items[1]
            prob_loss += loss_items[2]

        total_loss = giou_loss + conf_loss + prob_loss

        gradients = tape.gradient(total_loss, yolo.trainable_variables)
        optimizer.apply_gradients(zip(gradients, yolo.trainable_variables))

        # update learning rate
        # about warmup: https://arxiv.org/pdf/1812.01187.pdf&usg=ALkJrhglKOPDjNt6SHGbphTHyMcT0cuMJg
        global_steps.assign_add(1)
        if global_steps < warmup_steps and not TRAIN_TRANSFER:
            lr = global_steps / warmup_steps * TRAIN_LR_INIT
        else:
            lr = TRAIN_LR_END + 0.5 * (TRAIN_LR_INIT - TRAIN_LR_END)*(
                (1 + tf.cos((global_steps - warmup_steps) / (total_steps - warmup_steps) * np.pi)))
        optimizer.lr.assign(lr.numpy())

        # writing summary data
        with writer.as_default():
            tf.summary.scalar("lr", optimizer.lr, step=global_steps)
            tf.summary.scalar("loss/total_loss", total_loss, step=global_steps)
            tf.summary.scalar("loss/giou_loss", giou_loss, step=global_steps)
            tf.summary.scalar("loss/conf_loss", conf_loss, step=global_steps)
            tf.summary.scalar("loss/prob_loss", prob_loss, step=global_steps)
        writer.flush()
        
    return global_steps.numpy(), optimizer.lr.numpy(), giou_loss.numpy(), conf_loss.numpy(), prob_loss.numpy(), total_loss.numpy()

validate_writer = tf.summary.create_file_writer(logdir)#"./validate_log")
def validate_step(image_data, target):
    with tf.GradientTape() as tape:
        pred_result = yolo(image_data, training=False)
        giou_loss=conf_loss=prob_loss=0

        # optimizing process
        for i in range(3):
            conv, pred = pred_result[i*2], pred_result[i*2+1]
            loss_items = compute_loss(pred, conv, *target[i], i, CLASSES=TRAIN_CLASSES)
            giou_loss += loss_items[0]
            conf_loss += loss_items[1]
            prob_loss += loss_items[2]

        total_loss = giou_loss + conf_loss + prob_loss
        # writing summary data
        with validate_writer.as_default():
            tf.summary.scalar("lr", optimizer.lr, step=global_steps)
            tf.summary.scalar("validate_loss/total_loss", total_loss, step=global_steps)
            tf.summary.scalar("validate_loss/giou_loss", giou_loss, step=global_steps)
            tf.summary.scalar("validate_loss/conf_loss", conf_loss, step=global_steps)
            tf.summary.scalar("validate_loss/prob_loss", prob_loss, step=global_steps)
        validate_writer.flush()
        
    return giou_loss.numpy(), conf_loss.numpy(), prob_loss.numpy(), total_loss.numpy()


best_val_loss = 1000 # should be large at start

for epoch in range(TRAIN_EPOCHS):
    for image_data, target in trainset:
        results = train_step(image_data, target)
        cur_step = results[0]%steps_per_epoch
        print("epoch:{:2.0f} step:{:5.0f}/{}, lr:{:.6f}, giou_loss:{:7.2f}, conf_loss:{:7.2f}, prob_loss:{:7.2f}, total_loss:{:7.2f}"
              .format(epoch, cur_step, steps_per_epoch, results[1], results[2], results[3], results[4], results[5]))

    count, giou_val, conf_val, prob_val, total_val = 0, 0, 0, 0, 0
    for image_data, target in testset:
        results = validate_step(image_data, target)
        count += 1
        giou_val += results[0]
        conf_val += results[1]
        prob_val += results[2]
        total_val += results[3]
    print("\n\ngiou_val_loss:{:7.2f}, conf_val_loss:{:7.2f}, prob_val_loss:{:7.2f}, total_val_loss:{:7.2f}\n\n".
          format(giou_val/count, conf_val/count, prob_val/count, total_val/count))

    if save_checkpoints and not save_checkpoints:
        yolo.save_weights("./checkpoints/yolov3_custom"+"_val_loss_{:7.2f}".format(total_val/count))
    if save_best_only and best_val_loss>total_val/count:
        yolo.save_weights("./checkpoints/yolov3_custom")
        best_val_loss = total_val/count
    if not save_best_only and not save_checkpoints:
        yolo.save_weights("./checkpoints/yolov3_custom")
